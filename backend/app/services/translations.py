"""Translation service for bilingual API payloads."""

from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.kb_chunk import KBChunk
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.ticket import Ticket
from app.schemas.translation import (
    BilingualTextOut,
    KBChunkTranslationOut,
    ProblemTranslationOut,
    RecommendationTranslationOut,
    TicketCommentTranslationOut,
    TicketTranslationOut,
    TranslatedSuggestionOut,
    TranslationDatasetRequest,
    TranslationDatasetResponse,
    TranslationDatasetSummaryOut,
    TranslationScope,
    TranslationSuggestionRequest,
    TranslationSuggestionResponse,
)
from app.services.ai.llm import extract_json, ollama_generate

logger = logging.getLogger(__name__)

_JIRA_SOURCE_LABELS = {"jira", "jira_sync", "jira-import"}


def _strip_text(value: str | None) -> str:
    return str(value or "").strip()


def _translation_prompt(text: str) -> str:
    return (
        "You are a strict technical translator for ITSM and Jira content.\n"
        "Translate the INPUT into both English and French.\n"
        "Preserve IDs, keys, hostnames, versions, URLs, emails, and code-like tokens.\n"
        "Do not summarize and do not remove details.\n"
        'Return JSON only with this exact shape: {"en":"...", "fr":"..."}\n\n'
        f"INPUT:\n{text}"
    )


def _safe_translated_payload(raw: str, fallback: str) -> BilingualTextOut:
    parsed = extract_json(raw) or {}
    en = _strip_text(str(parsed.get("en") or ""))
    fr = _strip_text(str(parsed.get("fr") or ""))
    return BilingualTextOut(
        en=en or fallback,
        fr=fr or fallback,
    )


def translate_bilingual_text(text: str | None, *, cache: dict[str, BilingualTextOut]) -> BilingualTextOut:
    normalized = _strip_text(text)
    if not normalized:
        return BilingualTextOut(en="", fr="")
    cached = cache.get(normalized)
    if cached is not None:
        return cached

    translated = BilingualTextOut(en=normalized, fr=normalized)
    try:
        raw = ollama_generate(_translation_prompt(normalized), json_mode=True)
        translated = _safe_translated_payload(raw, normalized)
    except Exception as exc:  # noqa: BLE001
        logger.info("Bilingual translation fallback for text '%s': %s", normalized[:80], exc)
    cache[normalized] = translated
    return translated


def _jira_ticket_filter_clause():  # noqa: ANN202
    return or_(
        Ticket.source.in_(_JIRA_SOURCE_LABELS),
        Ticket.external_source.in_(_JIRA_SOURCE_LABELS),
        Ticket.jira_key.is_not(None),
    )


def _translate_optional(value: str | None, *, cache: dict[str, BilingualTextOut]) -> BilingualTextOut | None:
    normalized = _strip_text(value)
    if not normalized:
        return None
    return translate_bilingual_text(normalized, cache=cache)


def _translate_tickets(
    db: Session,
    *,
    payload: TranslationDatasetRequest,
    cache: dict[str, BilingualTextOut],
) -> tuple[list[TicketTranslationOut], int]:
    query = (
        db.query(Ticket)
        .options(joinedload(Ticket.comments))
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
    )
    if payload.jira_only:
        query = query.filter(_jira_ticket_filter_clause())
    rows = query.offset(payload.offset).limit(payload.limit_per_scope).all()

    translated_rows: list[TicketTranslationOut] = []
    comment_count = 0
    for ticket in rows:
        comments: list[TicketCommentTranslationOut] = []
        if payload.include_comments:
            for comment in ticket.comments or []:
                comments.append(
                    TicketCommentTranslationOut(
                        id=str(comment.id),
                        author=str(comment.author or ""),
                        jira_comment_id=_strip_text(comment.jira_comment_id) or None,
                        content=translate_bilingual_text(comment.content, cache=cache),
                    )
                )
                comment_count += 1
        translated_rows.append(
            TicketTranslationOut(
                id=str(ticket.id),
                source=str(ticket.source or "local"),
                jira_key=_strip_text(ticket.jira_key) or None,
                jira_issue_id=_strip_text(ticket.jira_issue_id) or None,
                title=translate_bilingual_text(ticket.title, cache=cache),
                description=translate_bilingual_text(ticket.description, cache=cache),
                resolution=_translate_optional(ticket.resolution, cache=cache),
                comments=comments,
            )
        )
    return translated_rows, comment_count


def _translate_problems(
    db: Session,
    *,
    payload: TranslationDatasetRequest,
    cache: dict[str, BilingualTextOut],
) -> list[ProblemTranslationOut]:
    query = db.query(Problem).order_by(Problem.updated_at.desc(), Problem.id.desc())
    if payload.jira_only:
        query = query.filter(Problem.tickets.any(_jira_ticket_filter_clause()))
    rows = query.offset(payload.offset).limit(payload.limit_per_scope).all()
    return [
        ProblemTranslationOut(
            id=str(problem.id),
            title=translate_bilingual_text(problem.title, cache=cache),
            root_cause=_translate_optional(problem.root_cause, cache=cache),
            workaround=_translate_optional(problem.workaround, cache=cache),
            permanent_fix=_translate_optional(problem.permanent_fix, cache=cache),
        )
        for problem in rows
    ]


def _jira_ticket_ids(db: Session) -> set[str]:
    rows = db.query(Ticket.id).filter(_jira_ticket_filter_clause()).all()
    return {str(ticket_id) for (ticket_id,) in rows}


def _translate_recommendations(
    db: Session,
    *,
    payload: TranslationDatasetRequest,
    cache: dict[str, BilingualTextOut],
) -> list[RecommendationTranslationOut]:
    query = db.query(Recommendation).order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
    rows = query.offset(payload.offset).limit(payload.limit_per_scope).all()
    jira_ids = _jira_ticket_ids(db) if payload.jira_only else set()
    translated_rows: list[RecommendationTranslationOut] = []

    for row in rows:
        related = [str(ticket_id).strip() for ticket_id in (row.related_tickets or []) if str(ticket_id).strip()]
        if payload.jira_only:
            if not related or not any(ticket_id in jira_ids for ticket_id in related):
                continue
        translated_rows.append(
            RecommendationTranslationOut(
                id=str(row.id),
                title=translate_bilingual_text(row.title, cache=cache),
                description=translate_bilingual_text(row.description, cache=cache),
                related_tickets=related,
            )
        )
    return translated_rows


def _translate_kb_chunks(
    db: Session,
    *,
    payload: TranslationDatasetRequest,
    cache: dict[str, BilingualTextOut],
) -> list[KBChunkTranslationOut]:
    query = db.query(KBChunk).order_by(KBChunk.updated_at.desc(), KBChunk.id.desc())
    if payload.jira_only:
        query = query.filter(
            or_(
                KBChunk.jira_key.is_not(None),
                KBChunk.source_type.in_(("jira_issue", "jira_comment")),
            )
        )
    rows = query.offset(payload.offset).limit(payload.limit_per_scope).all()
    return [
        KBChunkTranslationOut(
            id=int(row.id),
            source_type=str(row.source_type),
            jira_key=_strip_text(row.jira_key) or None,
            jira_issue_id=_strip_text(row.jira_issue_id) or None,
            comment_id=_strip_text(row.comment_id) or None,
            content=translate_bilingual_text(row.content, cache=cache),
        )
        for row in rows
    ]


def build_translated_dataset(db: Session, payload: TranslationDatasetRequest) -> TranslationDatasetResponse:
    cache: dict[str, BilingualTextOut] = {}
    scopes = list(payload.scopes)
    requested = set(scopes)

    tickets: list[TicketTranslationOut] = []
    problems: list[ProblemTranslationOut] = []
    recommendations: list[RecommendationTranslationOut] = []
    kb_chunks: list[KBChunkTranslationOut] = []
    comment_count = 0

    if TranslationScope.tickets in requested:
        tickets, comment_count = _translate_tickets(db, payload=payload, cache=cache)
    if TranslationScope.problems in requested:
        problems = _translate_problems(db, payload=payload, cache=cache)
    if TranslationScope.recommendations in requested:
        recommendations = _translate_recommendations(db, payload=payload, cache=cache)
    if TranslationScope.kb_chunks in requested:
        kb_chunks = _translate_kb_chunks(db, payload=payload, cache=cache)

    summary = TranslationDatasetSummaryOut(
        requested_scopes=scopes,
        tickets=len(tickets),
        ticket_comments=comment_count,
        problems=len(problems),
        recommendations=len(recommendations),
        kb_chunks=len(kb_chunks),
        unique_texts_translated=len(cache),
    )
    return TranslationDatasetResponse(
        summary=summary,
        translation_provider=f"ollama:{settings.OLLAMA_MODEL}",
        tickets=tickets,
        problems=problems,
        recommendations=recommendations,
        kb_chunks=kb_chunks,
    )


def build_translated_suggestions(payload: TranslationSuggestionRequest) -> TranslationSuggestionResponse:
    cache: dict[str, BilingualTextOut] = {}
    seen: set[str] = set()
    translated: list[TranslatedSuggestionOut] = []

    for suggestion in payload.suggestions:
        text = _strip_text(suggestion)
        if not text:
            continue
        dedupe_key = text.casefold()
        if payload.dedupe and dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        translated.append(
            TranslatedSuggestionOut(
                source_text=text,
                translations=translate_bilingual_text(text, cache=cache),
            )
        )

    return TranslationSuggestionResponse(
        translation_provider=f"ollama:{settings.OLLAMA_MODEL}",
        count=len(translated),
        suggestions=translated,
    )
