"""Shared filtering helpers for ticket-to-ticket similarity surfaces."""

from __future__ import annotations

from typing import Any

from app.services.ai.routing_validation import validate_ticket_routing_for_ticket
from app.services.ai.service_requests import service_request_profile_from_ticket, service_request_profile_similarity


def select_visible_similar_ticket_matches(
    *,
    source_ticket: Any | None,
    visible_tickets: list[Any] | None,
    retrieval_rows: list[dict[str, Any]] | None,
    limit: int = 5,
    min_score: float = 0.3,
) -> list[dict[str, Any]]:
    """Filter raw retrieval rows down to the same visible matches shown in ticket detail."""

    if source_ticket is None:
        return []

    source_ticket_id = str(getattr(source_ticket, "id", "") or "").strip()
    if not source_ticket_id:
        return []

    visible = list(visible_tickets or [])
    visible_by_id = {
        str(item.id): item
        for item in visible
        if getattr(item, "id", None)
    }
    if not visible_by_id:
        return []

    base_is_service_request = validate_ticket_routing_for_ticket(source_ticket).use_service_request_guidance
    base_profile = service_request_profile_from_ticket(source_ticket) if base_is_service_request else None

    matches: list[dict[str, Any]] = []
    for row in list(retrieval_rows or []):
        similar_id = str(row.get("id") or "").strip()
        if not similar_id or similar_id == source_ticket_id:
            continue
        candidate = visible_by_id.get(similar_id)
        if candidate is None:
            continue
        if base_is_service_request and not validate_ticket_routing_for_ticket(candidate).use_service_request_guidance:
            continue
        if base_is_service_request:
            candidate_profile = service_request_profile_from_ticket(candidate)
            profile_similarity = service_request_profile_similarity(base_profile, candidate_profile)
            if profile_similarity < 0.2:
                continue
        similarity_score = round(float(row.get("similarity_score") or 0.0), 4)
        if similarity_score < min_score:
            continue
        matches.append(
            {
                "ticket": candidate,
                "row": row,
                "similarity_score": similarity_score,
            }
        )
        if len(matches) >= limit:
            break
    return matches
