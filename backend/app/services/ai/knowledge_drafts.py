from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from app.services.ai.llm import extract_json, ollama_generate

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class KnowledgeDraft:
    ticket_id: str
    title: str
    summary: str
    symptoms: list[str]
    root_cause: str | None
    workaround: str | None
    resolution_steps: list[str]
    tags: list[str]
    review_note: str
    confidence: float
    source: str
    generated_at: dt.datetime


def _clean_text(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or fallback


def _dedupe_preserve(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        cleaned = _clean_text(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def _split_sentences(text: str, *, limit: int) -> list[str]:
    normalized = _clean_text(text)
    if not normalized:
        return []
    pieces = [piece.strip(" -") for piece in _SENTENCE_SPLIT_RE.split(normalized) if piece.strip()]
    return _dedupe_preserve(pieces, limit=limit)


def _fallback_draft(ticket: dict[str, Any], comments: list[dict[str, Any]], *, lang: str) -> KnowledgeDraft:
    title = _clean_text(ticket.get("title"), fallback="Resolved ticket knowledge draft")
    description = _clean_text(ticket.get("description"))
    resolution = _clean_text(ticket.get("resolution"))
    comment_texts = [
        _clean_text(comment.get("body") or comment.get("content") or comment.get("text"))
        for comment in comments or []
    ]
    recent_comment = next((item for item in reversed(comment_texts) if item), "")
    symptoms = _split_sentences(description or title, limit=3)
    steps_source = resolution or recent_comment or description
    resolution_steps = _split_sentences(steps_source, limit=4)
    if not resolution_steps and description:
        resolution_steps = [description[:200]]
    tags = _dedupe_preserve(
        [
            str(ticket.get("category") or ""),
            str(ticket.get("priority") or ""),
            *(ticket.get("tags") or []),
        ],
        limit=6,
    )
    review_note = (
        "Brouillon IA a valider avant publication dans la base de connaissance."
        if lang == "fr"
        else "AI draft to validate before publishing to the knowledge base."
    )
    root_cause = (
        resolution[:220]
        if resolution
        else (
            "A confirmer a partir du ticket resolu et des commentaires."
            if lang == "fr"
            else "To confirm from the resolved ticket and its comments."
        )
    )
    workaround = recent_comment[:220] if recent_comment and recent_comment != resolution else None
    summary = resolution or description or title
    return KnowledgeDraft(
        ticket_id=str(ticket.get("id") or "").strip(),
        title=(f"Base de connaissance - {title}" if lang == "fr" else f"Knowledge base - {title}")[:140],
        summary=summary[:400],
        symptoms=symptoms,
        root_cause=root_cause,
        workaround=workaround,
        resolution_steps=resolution_steps,
        tags=tags,
        review_note=review_note,
        confidence=0.42 if resolution else 0.28,
        source="fallback",
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


async def generate_ticket_knowledge_draft(
    *,
    ticket: dict[str, Any],
    comments: list[dict[str, Any]],
    lang: str = "fr",
) -> KnowledgeDraft:
    fallback = _fallback_draft(ticket, comments, lang=lang)
    title = _clean_text(ticket.get("title"))
    description = _clean_text(ticket.get("description"))
    resolution = _clean_text(ticket.get("resolution"))
    if not title or not (description or resolution):
        return fallback

    recent_comments = [
        _clean_text(comment.get("body") or comment.get("content") or comment.get("text"))
        for comment in comments[-5:]
        if _clean_text(comment.get("body") or comment.get("content") or comment.get("text"))
    ]
    prompt = (
        "You are an ITSM knowledge manager. Create a concise reusable knowledge-base draft in valid JSON only.\n"
        "Return an object with keys: title, summary, symptoms, root_cause, workaround, resolution_steps, tags, review_note.\n"
        "Rules:\n"
        "- Keep content grounded in the resolved ticket.\n"
        "- symptoms and resolution_steps must be arrays of short strings.\n"
        "- Do not invent actions not mentioned in the ticket or comments.\n"
        "- review_note must remind the agent to validate before publishing.\n\n"
        f"Language: {'French' if lang == 'fr' else 'English'}\n"
        f"Ticket id: {ticket.get('id')}\n"
        f"Title: {title}\n"
        f"Description: {description[:900]}\n"
        f"Resolution: {resolution[:900]}\n"
        f"Category: {_clean_text(ticket.get('category'))}\n"
        f"Priority: {_clean_text(ticket.get('priority'))}\n"
        f"Comments:\n- " + "\n- ".join(recent_comments[:5])
    )
    raw = ollama_generate(prompt, json_mode=True)
    parsed = extract_json(raw or "")
    if not isinstance(parsed, dict):
        return fallback

    symptoms = parsed.get("symptoms") if isinstance(parsed.get("symptoms"), list) else []
    resolution_steps = parsed.get("resolution_steps") if isinstance(parsed.get("resolution_steps"), list) else []
    tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
    root_cause = _clean_text(parsed.get("root_cause")) or fallback.root_cause
    workaround = _clean_text(parsed.get("workaround")) or fallback.workaround
    summary = _clean_text(parsed.get("summary")) or fallback.summary
    draft_title = _clean_text(parsed.get("title")) or fallback.title
    review_note = _clean_text(parsed.get("review_note")) or fallback.review_note

    cleaned_symptoms = _dedupe_preserve([str(item) for item in symptoms], limit=4) or fallback.symptoms
    cleaned_steps = _dedupe_preserve([str(item) for item in resolution_steps], limit=5) or fallback.resolution_steps
    cleaned_tags = _dedupe_preserve([str(item) for item in tags], limit=6) or fallback.tags

    return KnowledgeDraft(
        ticket_id=fallback.ticket_id,
        title=draft_title[:140],
        summary=summary[:400],
        symptoms=cleaned_symptoms,
        root_cause=root_cause[:260] if root_cause else None,
        workaround=workaround[:260] if workaround else None,
        resolution_steps=cleaned_steps,
        tags=cleaned_tags,
        review_note=review_note[:220],
        confidence=0.74 if resolution else 0.58,
        source="llm",
        generated_at=dt.datetime.now(dt.timezone.utc),
    )
