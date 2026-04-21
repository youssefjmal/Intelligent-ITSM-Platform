"""
AI ticket summarization service.

Generates concise, context-enriched summaries of IT tickets by combining
the ticket's own fields with RAG-retrieved similar tickets for context.

Pipeline:
1. Extract ticket signals: title, description, category, type, priority,
   status, assignee, reporter, created_at
2. Run unified_retrieve() to find similar tickets (max SUMMARY_MAX_SIMILAR_TICKETS,
   resolved first)
3. Build prompt with ticket fields + similar ticket abstracts as context
4. Call LLM to generate summary
5. Validate: no more than SUMMARY_MAX_LENGTH_CHARS
6. Persist to tickets.ai_summary + tickets.summary_generated_at
7. Return SummaryResult

Caching: TTL-based (SUMMARY_CACHE_TTL_MINUTES). Invalidated on comment,
status change, or description update. Stale summary kept as fallback if LLM
regeneration fails.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field

from app.schemas.ai import RetrievalResult
from app.services.ai.retrieval import unified_retrieve

log = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    """
    Result of AI ticket summarization.

    Fields:
        summary: Generated summary text. 2-4 sentences covering what the
            issue is, who is affected, current status, and if similar resolved
            tickets exist — what typically resolves it.
        similar_ticket_count: Number of similar tickets used as RAG context.
            0 means summary is based on ticket fields only.
        used_ticket_ids: List of similar ticket IDs that informed the summary.
        generated_at: Timestamp of generation. Stored in DB.
        is_cached: True if result came from DB cache.
        language: Language the summary was generated in.
    """

    summary: str
    similar_ticket_count: int
    used_ticket_ids: list[str] = field(default_factory=list)
    generated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    is_cached: bool = False
    language: str = "fr"


def _is_cache_fresh(generated_at: dt.datetime | None) -> bool:
    """Return True if the cached summary is within the TTL window.

    Args:
        generated_at: The timestamp the summary was last generated.
    Returns:
        True if within SUMMARY_CACHE_TTL_MINUTES, False otherwise.
    """
    if generated_at is None:
        return False
    from app.services.ai.calibration import SUMMARY_CACHE_TTL_MINUTES

    now = dt.datetime.now(dt.timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=dt.timezone.utc)
    age_minutes = (now - generated_at).total_seconds() / 60.0
    return age_minutes < SUMMARY_CACHE_TTL_MINUTES


def _build_summary_prompt(
    ticket: dict,
    similar_tickets: list[dict],
    language: str = "fr",
) -> tuple[str, str]:
    """Build system + user prompt for ticket summarization.

    Instructs the LLM to write 2-4 sentences covering what the issue is,
    who is affected, current status, and resolution hint from similar tickets.

    Args:
        ticket: Ticket dict with all fields.
        similar_tickets: Similar ticket dicts (max 3), each with id, title,
            status, resolution (if resolved).
        language: "fr" or "en".
    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    lang_name = "French" if language == "fr" else "English"
    system_prompt = (
        f"You are an ITSM assistant that writes concise ticket summaries in {lang_name}.\n"
        "Rules:\n"
        "- Write exactly 2-4 sentences.\n"
        "- Cover: what the issue is, who is affected, current status.\n"
        "- If similar resolved tickets are provided, mention what typically resolves it "
        "using cautious language ('similar past incidents were resolved by...').\n"
        "- Use plain language readable by an IT manager.\n"
        "- Do NOT repeat the ticket ID or category label verbatim.\n"
        "- Do NOT fabricate names, IDs, or system names not in the input.\n"
        f"- Respond in {lang_name} only."
    )
    ticket_section = (
        f"Ticket: {ticket.get('title', '')}\n"
        f"Description: {(ticket.get('description', '') or '')[:400]}\n"
        f"Category: {ticket.get('category', '')}\n"
        f"Priority: {ticket.get('priority', '')}\n"
        f"Status: {ticket.get('status', '')}\n"
        f"Assignee: {ticket.get('assignee', '')}\n"
        f"Reporter: {ticket.get('reporter', '')}"
    )
    similar_section = ""
    if similar_tickets:
        lines = ["Similar past tickets:"]
        for sim in similar_tickets:
            resolution = str(sim.get("resolution") or sim.get("description") or "")[:120]
            lines.append(f"- {sim.get('id', '')}: {sim.get('title', '')} [{sim.get('status', '')}] — {resolution}")
        similar_section = "\n" + "\n".join(lines)
    user_prompt = f"{ticket_section}{similar_section}\n\nWrite the summary now:"
    return system_prompt, user_prompt


def _clean_summary_text(text: str, *, max_length: int) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def _truncate_words(text: str, *, max_words: int) -> str:
    words = [word for word in str(text or "").strip().split() if word]
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:-") + "..."


def _deterministic_summary(
    ticket: dict,
    similar_tickets: list[dict],
    *,
    language: str,
    max_length: int,
) -> str:
    title = str(ticket.get("title") or "").strip()
    description = _truncate_words(str(ticket.get("description") or "").strip(), max_words=24)
    status = str(ticket.get("status") or "").strip()
    assignee = str(ticket.get("assignee") or "").strip()
    reporter = str(ticket.get("reporter") or "").strip()

    if language == "fr":
        sentence_1 = (
            f"Le ticket concerne {title.lower()}."
            if title
            else "Le ticket concerne un incident en cours d'analyse."
        )
        sentence_2_parts: list[str] = []
        if description:
            sentence_2_parts.append(description)
        if status:
            sentence_2_parts.append(f"Statut actuel : {status}.")
        if assignee:
            sentence_2_parts.append(f"Assigne a {assignee}.")
        elif reporter:
            sentence_2_parts.append(f"Signale par {reporter}.")
        sentence_2 = " ".join(part for part in sentence_2_parts if part).strip()
        if similar_tickets:
            resolution_hint = _truncate_words(str(similar_tickets[0].get("resolution") or ""), max_words=18)
            if resolution_hint:
                sentence_3 = f"Des tickets similaires resolus indiquent souvent : {resolution_hint}"
            else:
                sentence_3 = "Des tickets similaires resolus existent et peuvent orienter le diagnostic."
            summary = " ".join(part for part in [sentence_1, sentence_2, sentence_3] if part)
        else:
            summary = " ".join(part for part in [sentence_1, sentence_2] if part)
    else:
        sentence_1 = (
            f"This ticket concerns {title.lower()}."
            if title
            else "This ticket concerns an issue still under review."
        )
        sentence_2_parts = []
        if description:
            sentence_2_parts.append(description)
        if status:
            sentence_2_parts.append(f"Current status: {status}.")
        if assignee:
            sentence_2_parts.append(f"Assigned to {assignee}.")
        elif reporter:
            sentence_2_parts.append(f"Reported by {reporter}.")
        sentence_2 = " ".join(part for part in sentence_2_parts if part).strip()
        if similar_tickets:
            resolution_hint = _truncate_words(str(similar_tickets[0].get("resolution") or ""), max_words=18)
            if resolution_hint:
                sentence_3 = f"Similar resolved tickets suggest this is often addressed by {resolution_hint}"
            else:
                sentence_3 = "Similar resolved tickets exist and can help guide the diagnosis."
            summary = " ".join(part for part in [sentence_1, sentence_2, sentence_3] if part)
        else:
            summary = " ".join(part for part in [sentence_1, sentence_2] if part)
    return _clean_summary_text(summary, max_length=max_length)


def _looks_like_usable_summary(summary: str) -> bool:
    cleaned = str(summary or "").strip()
    if len(cleaned) < 24:
        return False
    sentence_parts = [part for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    return len(sentence_parts) >= 1


async def generate_ticket_summary(
    ticket: dict,
    db=None,
    force_regenerate: bool = False,
    language: str = "fr",
) -> SummaryResult:
    """Generate or retrieve a cached AI summary for a ticket.

    Returns cached result if summary_generated_at is within
    SUMMARY_CACHE_TTL_MINUTES and force_regenerate is False.
    Otherwise runs the full pipeline and persists the result.

    Never raises — returns SummaryResult with summary="" and
    similar_ticket_count=0 on any failure.

    Args:
        ticket: Full ticket dict including all fields and recent comments.
        db: SQLAlchemy session for cache read/write. Optional — if None,
            skips DB persistence (useful in tests).
        force_regenerate: If True, bypasses cache and regenerates.
        language: "fr" or "en". Inferred from ticket content if possible.
    Returns:
        SummaryResult always. Never raises.
    """
    from app.services.ai.calibration import SUMMARY_CACHE_TTL_MINUTES, SUMMARY_MAX_SIMILAR_TICKETS, SUMMARY_MAX_LENGTH_CHARS  # noqa: F401

    ticket_id = str(ticket.get("id") or "")

    # Check DB cache first
    if db is not None and not force_regenerate:
        try:
            from app.models.ticket import Ticket as TicketModel
            db_ticket = db.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if db_ticket is not None:
                cached_summary = getattr(db_ticket, "ai_summary", None)
                cached_at = getattr(db_ticket, "summary_generated_at", None)
                if cached_summary and _is_cache_fresh(cached_at):
                    return SummaryResult(
                        summary=cached_summary,
                        similar_ticket_count=0,
                        used_ticket_ids=[],
                        generated_at=cached_at if cached_at else dt.datetime.now(dt.timezone.utc),
                        is_cached=True,
                        language=language,
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("summarization: cache read failed for %s: %s", ticket_id, exc)

    # Retrieve similar tickets for context
    similar_tickets: list[dict] = []
    used_ids: list[str] = []
    try:
        query_str = f"{ticket.get('title', '')} {ticket.get('description', '')}".strip()
        retrieval = unified_retrieve(
            db,
            query=query_str,
            visible_tickets=[],
            top_k=SUMMARY_MAX_SIMILAR_TICKETS + 2,
            exclude_ids=[ticket_id] if ticket_id else [],
        )
        retrieval = RetrievalResult.coerce(retrieval)
        candidates = list(retrieval.similar_tickets or [])
        # Prefer resolved tickets
        resolved = [c for c in candidates if str(c.get("status", "")).lower() in {"resolved", "closed"}]
        others = [c for c in candidates if c not in resolved]
        picked = (resolved + others)[:SUMMARY_MAX_SIMILAR_TICKETS]
        for c in picked:
            sim_id = str(c.get("id") or c.get("ticket_id") or "")
            if sim_id and sim_id != ticket_id:
                similar_tickets.append({
                    "id": sim_id,
                    "title": str(c.get("title") or ""),
                    "status": str(c.get("status") or ""),
                    "resolution": str(c.get("resolution") or c.get("description") or "")[:120],
                })
                used_ids.append(sim_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("summarization: retrieval failed for %s: %s", ticket_id, exc)

    # Call LLM
    summary_text = ""
    deterministic_fallback = _deterministic_summary(
        ticket,
        similar_tickets,
        language=language,
        max_length=SUMMARY_MAX_LENGTH_CHARS,
    )
    try:
        from app.services.ai.llm import ollama_generate
        system_prompt, user_prompt = _build_summary_prompt(ticket, similar_tickets, language)
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        raw = ollama_generate(full_prompt, json_mode=False)
        summary_text = _clean_summary_text(str(raw or ""), max_length=SUMMARY_MAX_LENGTH_CHARS)
        if not _looks_like_usable_summary(summary_text):
            raise RuntimeError("summary_llm_empty_or_too_short")
    except Exception as exc:  # noqa: BLE001
        log.warning("summarization: LLM call failed for %s: %s", ticket_id, exc)
        # Return stale cache as fallback if available
        if db is not None:
            try:
                from app.models.ticket import Ticket as TicketModel
                db_ticket = db.query(TicketModel).filter(TicketModel.id == ticket_id).first()
                stale = getattr(db_ticket, "ai_summary", None) if db_ticket else None
                if stale:
                    return SummaryResult(
                        summary=stale, similar_ticket_count=0, used_ticket_ids=[],
                        generated_at=dt.datetime.now(dt.timezone.utc), is_cached=True, language=language,
                    )
            except Exception:  # noqa: BLE001
                pass
        summary_text = deterministic_fallback

    now = dt.datetime.now(dt.timezone.utc)

    # Persist to DB
    if db is not None and summary_text:
        try:
            from app.models.ticket import Ticket as TicketModel
            db_ticket = db.query(TicketModel).filter(TicketModel.id == ticket_id).first()
            if db_ticket is not None:
                db_ticket.ai_summary = summary_text
                db_ticket.summary_generated_at = now
                db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("summarization: DB write failed for %s: %s", ticket_id, exc)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return SummaryResult(
        summary=summary_text,
        similar_ticket_count=len(used_ids),
        used_ticket_ids=used_ids,
        generated_at=now,
        is_cached=False,
        language=language,
    )


@dataclass
class ResolutionSuggestion:
    """
    AI-suggested resolution text for a closing ticket.

    Fields:
        text: Suggested resolution description. Empty string if
            no suggestion could be generated.
        confidence: Float 0-1. Low when based on generic patterns,
            higher when grounded in specific comment content.
        based_on_comments: True if suggestion used comment content.
        based_on_feedback: True if suggestion used applied recommendations.
    """

    text: str
    confidence: float
    based_on_comments: bool
    based_on_feedback: bool


async def generate_resolution_suggestion(
    ticket: dict,
    comments: list[dict],
) -> ResolutionSuggestion:
    """
    Generate a suggested resolution text for a ticket being closed.

    Called when an agent changes ticket status to "resolved" and the
    resolution field is empty or very short (< 20 characters).

    Uses the last 5 comments and any applied recommendations from
    ai_solution_feedback (feedback_type="applied") to construct a
    concise resolution description.

    The suggestion:
    - Is 2-3 sentences maximum
    - Uses past tense ("The issue was resolved by...")
    - References specific actions from comments when available
    - Never fabricates actions not present in input
    - Is framed as a draft — agent must confirm before saving

    Args:
        ticket: Full ticket dict with at minimum "title" and "description".
        comments: List of all ticket comments ordered by created_at.

    Returns:
        ResolutionSuggestion with text and confidence.
        Returns ResolutionSuggestion(text="", confidence=0.0,
        based_on_comments=False, based_on_feedback=False) on failure.
        Never raises.

    Edge cases:
        - No comments: generates generic suggestion from title only
        - LLM timeout: returns empty suggestion
        - Comments with empty body: skipped
    """
    try:
        title = str(ticket.get("title") or "").strip()
        description = str(ticket.get("description") or "").strip()
        if not title:
            return ResolutionSuggestion(
                text="", confidence=0.0, based_on_comments=False, based_on_feedback=False
            )

        # Collect last 5 non-empty comments
        recent_comments: list[str] = []
        for c in (comments or [])[-5:]:
            body = str(
                c.get("body")
                or c.get("content")
                or c.get("text")
                or ""
            ).strip()
            if body and len(body) > 10:
                recent_comments.append(body[:400])

        based_on_comments = bool(recent_comments)

        # Build context block
        comment_block = ""
        if recent_comments:
            comment_block = "\n\nCommentaires récents sur ce ticket:\n" + "\n- ".join(
                [""] + recent_comments
            )

        prompt = (
            "Tu es un assistant ITSM. L'agent vient de résoudre ce ticket.\n\n"
            f"Titre: {title}\n"
            f"Description: {description[:400]}\n"
            f"{comment_block}\n\n"
            "Rédige en 2-3 phrases maximum une description de résolution au passé "
            "(exemple: 'Le problème a été résolu en...'). "
            "Base-toi uniquement sur les actions mentionnées dans les commentaires si disponibles. "
            "Ne fabrique aucune action non mentionnée. "
            "Commence par 'Le problème a été résolu' ou 'L\\'incident a été résolu'.\n\n"
            "Retourne UNIQUEMENT la description de résolution, sans titre ni liste."
        )

        from app.services.ai.llm import ollama_generate as _ollama_generate

        raw = _ollama_generate(prompt, json_mode=False)
        text = str(raw or "").strip()

        if not text or len(text) < 20:
            return ResolutionSuggestion(
                text="",
                confidence=0.0,
                based_on_comments=based_on_comments,
                based_on_feedback=False,
            )

        # Truncate to 3 sentences max
        import re as _re

        sentences = _re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) > 3:
            text = " ".join(sentences[:3])

        confidence = 0.72 if based_on_comments else 0.38

        return ResolutionSuggestion(
            text=text[:600],
            confidence=round(confidence, 4),
            based_on_comments=based_on_comments,
            based_on_feedback=False,
        )

    except Exception as exc:  # noqa: BLE001
        log.warning("generate_resolution_suggestion failed: %s", exc)
        return ResolutionSuggestion(
            text="", confidence=0.0, based_on_comments=False, based_on_feedback=False
        )


def invalidate_ticket_summary(ticket_id: str, db=None) -> None:
    """Mark a ticket's summary as stale by clearing summary_generated_at.

    Causes the next page load to regenerate. Does NOT delete ai_summary —
    the stale text is kept as fallback if LLM regeneration fails.

    Args:
        ticket_id: ID of the ticket to invalidate.
        db: SQLAlchemy session. If None, logs a warning and returns.
    Returns:
        None. Logs a warning if ticket not found but does not raise.
    """
    if db is None:
        log.warning("invalidate_ticket_summary: no db session provided for %s", ticket_id)
        return
    try:
        from app.models.ticket import Ticket as TicketModel
        db_ticket = db.query(TicketModel).filter(TicketModel.id == ticket_id).first()
        if db_ticket is None:
            log.warning("invalidate_ticket_summary: ticket %s not found", ticket_id)
            return
        db_ticket.summary_generated_at = None
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("invalidate_ticket_summary: failed for %s: %s", ticket_id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
