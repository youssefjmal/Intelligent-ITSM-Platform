"""Duplicate ticket detection before creation using semantic retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas.ai import RetrievalResult
from app.services.ai.calibration import DUPLICATE_SIMILARITY_THRESHOLD, MAX_DUPLICATE_CANDIDATES
from app.services.ai.retrieval import unified_retrieve
from app.models.enums import TicketStatus

logger = logging.getLogger(__name__)

_OPEN_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}


@dataclass
class DuplicateCandidate:
    """
    A potentially duplicate ticket detected before creation.

    Fields:
        ticket_id: ID of the existing open ticket.
        title: Title of the existing ticket.
        status: Current status of the existing ticket.
        assignee: Current assignee or None.
        similarity_score: Float 0-1, higher = more similar.
        match_reason: Short explanation of why this was flagged.
        url: Frontend URL to view the ticket (/tickets/{id}).
    """

    ticket_id: str
    title: str
    status: str
    assignee: str | None
    similarity_score: float
    match_reason: str
    url: str


async def detect_duplicate_tickets(
    db: Session,
    title: str,
    description: str,
    category: str | None = None,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> list[DuplicateCandidate]:
    """
    Detect potentially duplicate open tickets before creation.

    Uses unified_retrieve() with the draft ticket context to find
    open tickets with high semantic + lexical overlap. Only open
    and in-progress tickets are returned — resolved/closed tickets
    are excluded.

    Args:
        db: Database session.
        title: Draft ticket title.
        description: Draft ticket description.
        category: Optional category hint for retrieval focus.
        threshold: Minimum similarity_score to flag as duplicate.
            Defaults to DUPLICATE_SIMILARITY_THRESHOLD.

    Returns:
        List of DuplicateCandidate ordered by similarity desc.
        Empty list if no duplicates found or on any error.
        Maximum MAX_DUPLICATE_CANDIDATES results returned.

    Edge cases:
        - Empty title/description: returns empty list
        - unified_retrieve failure: returns empty list, logs warning
        - threshold > 1.0 or < 0.0: clamped automatically
    """
    try:
        title_clean = str(title or "").strip()
        desc_clean = str(description or "").strip()
        if not title_clean or not desc_clean:
            return []

        threshold = max(0.0, min(1.0, float(threshold)))
        query_str = title_clean
        if desc_clean:
            query_str = f"{title_clean}. {desc_clean[:300]}"
        if category:
            query_str = f"[{category}] {query_str}"

        retrieval_result = RetrievalResult.coerce(unified_retrieve(
            db,
            query=query_str,
            visible_tickets=[],
            top_k=MAX_DUPLICATE_CANDIDATES * 3,
        ))

        raw_tickets = retrieval_result.similar_tickets or []

        candidates = []
        for item in raw_tickets:
            if isinstance(item, dict):
                ticket_id = str(item.get("id") or "").strip()
                item_title = str(item.get("title") or "").strip()
                item_status_raw = str(item.get("status") or "").strip().lower()
                item_assignee = item.get("assignee") or None
                score = float(
                    item.get("similarity_score")
                    or item.get("coherence_score")
                    or 0.0
                )
            else:
                ticket_id = str(getattr(item, "id", "") or "").strip()
                item_title = str(getattr(item, "title", "") or "").strip()
                item_status_raw = str(getattr(item, "status", "") or "").strip().lower()
                item_assignee = getattr(item, "assignee", None) or None
                score = float(
                    getattr(item, "similarity_score", 0)
                    or getattr(item, "coherence_score", 0)
                    or 0.0
                )

            if not ticket_id or not item_title:
                continue

            # Only flag open/active tickets as duplicates
            try:
                status_enum = TicketStatus(item_status_raw)
                if status_enum not in _OPEN_STATUSES:
                    continue
            except ValueError:
                # Unknown status — skip
                continue

            if score < threshold:
                continue

            # Build a human-readable match reason
            if score >= 0.90:
                reason = "Titre et description très similaires."
            elif score >= 0.80:
                reason = "Sujet similaire détecté."
            else:
                reason = "Possible doublon — vérifiez avant de créer."

            candidates.append(
                DuplicateCandidate(
                    ticket_id=ticket_id,
                    title=item_title,
                    status=item_status_raw,
                    assignee=str(item_assignee) if item_assignee else None,
                    similarity_score=round(score, 4),
                    match_reason=reason,
                    url=f"/tickets/{ticket_id}",
                )
            )

        # Sort by score desc, limit to MAX_DUPLICATE_CANDIDATES
        candidates.sort(key=lambda c: c.similarity_score, reverse=True)
        return candidates[:MAX_DUPLICATE_CANDIDATES]

    except Exception as exc:  # noqa: BLE001
        logger.warning("detect_duplicate_tickets failed: %s", exc)
        return []
