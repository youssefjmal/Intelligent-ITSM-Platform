"""Global search endpoint across tickets, problems, and KB."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.models.user import User

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])
logger = logging.getLogger(__name__)

_SEARCH_MAX_LIMIT = 20
_SEARCH_DEFAULT_LIMIT = 5


def _excerpt(text: str | None, query: str, max_len: int = 120) -> str:
    """
    Build a ~120 char snippet from text, trying to include the query terms.

    Args:
        text: Source text to excerpt from.
        query: Search query — used to find a relevant window.
        max_len: Maximum length of the excerpt.

    Returns:
        Excerpt string. Empty string if text is None or empty.
    """
    if not text:
        return ""
    text = text.strip()
    lower_text = text.lower()
    lower_query = query.lower().strip()
    idx = lower_text.find(lower_query)
    if idx == -1:
        # Try first word of query
        first_word = lower_query.split()[0] if lower_query.split() else ""
        idx = lower_text.find(first_word) if first_word else -1
    if idx > 0:
        start = max(0, idx - 30)
        snippet = text[start : start + max_len]
        if start > 0:
            snippet = "..." + snippet.lstrip()
    else:
        snippet = text[:max_len]
    if len(snippet) < len(text) and not snippet.endswith("..."):
        snippet = snippet.rstrip() + "..."
    return snippet


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
    types: str = Query(
        default="tickets,problems",
        description="Comma-separated: tickets,problems,kb",
    ),
    limit: int = Query(default=_SEARCH_DEFAULT_LIMIT, ge=1, le=_SEARCH_MAX_LIMIT),
    status: str | None = Query(default=None, description="Optional ticket status filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Global search across tickets, problems, and KB articles.

    Searches ticket title+description, problem title+root_cause, and kb content.
    Returns grouped results per type with a 120-char excerpt.

    Args:
        q: Search query. Minimum 2 characters.
        types: Comma-separated list of types to search (tickets,problems,kb).
        limit: Max results per type (1-20, default 5).
        status: Optional status filter for tickets.
        db: Database session.
        current_user: Authenticated user.

    Returns:
        Dict with query, results (grouped by type), and total_count.

    Edge cases:
        - Query < 2 chars: returns 400 (enforced by Query validator).
        - Unknown type in types: silently ignored.
        - DB error: returns empty results for that type, logs warning.
    """
    q_stripped = str(q or "").strip()
    requested_types = {
        t.strip().lower()
        for t in (types or "tickets,problems").split(",")
        if t.strip()
    }
    limit = max(1, min(_SEARCH_MAX_LIMIT, limit))

    results: dict[str, list[dict]] = {"tickets": [], "problems": [], "kb": []}

    # --- Tickets ---
    if "tickets" in requested_types:
        try:
            like_q = f"%{q_stripped}%"
            q_tickets = db.query(Ticket).filter(
                or_(
                    Ticket.title.ilike(like_q),
                    Ticket.description.ilike(like_q),
                )
            )
            if status:
                q_tickets = q_tickets.filter(Ticket.status == status)
            ticket_rows = (
                q_tickets.order_by(Ticket.updated_at.desc()).limit(limit).all()
            )
            for t in ticket_rows:
                excerpt = _excerpt(t.description or t.title or "", q_stripped)
                results["tickets"].append(
                    {
                        "id": str(t.id),
                        "type": "ticket",
                        "title": str(t.title or ""),
                        "excerpt": excerpt,
                        "status": str(
                            t.status.value
                            if hasattr(t.status, "value")
                            else t.status or ""
                        ),
                        "priority": str(
                            t.priority.value
                            if hasattr(t.priority, "value")
                            else t.priority or ""
                        ),
                        "url": f"/tickets/{t.id}",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Search tickets failed: %s", exc)

    # --- Problems ---
    if "problems" in requested_types:
        try:
            like_q = f"%{q_stripped}%"
            problem_rows = (
                db.query(Problem)
                .filter(
                    or_(
                        Problem.title.ilike(like_q),
                        Problem.root_cause.ilike(like_q),
                        Problem.workaround.ilike(like_q),
                    )
                )
                .order_by(Problem.updated_at.desc())
                .limit(limit)
                .all()
            )
            for p in problem_rows:
                excerpt = _excerpt(
                    p.root_cause or p.workaround or p.title or "", q_stripped
                )
                results["problems"].append(
                    {
                        "id": str(p.id),
                        "type": "problem",
                        "title": str(p.title or ""),
                        "excerpt": excerpt,
                        "status": str(
                            p.status.value
                            if hasattr(p.status, "value")
                            else p.status or ""
                        ),
                        "priority": str(
                            getattr(p, "severity", None) or getattr(p, "priority", "") or ""
                        ),
                        "url": f"/problems/{p.id}",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Search problems failed: %s", exc)

    # --- KB (skip if not requested — no kb table currently) ---
    # kb search is a future enhancement; return empty list for now

    total_count = sum(len(v) for v in results.values())
    return {
        "query": q_stripped,
        "results": results,
        "total_count": total_count,
    }
