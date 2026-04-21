"""Ticket CRUD endpoints and analytics."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Body, Depends, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rbac import can_edit_ticket_triage, can_resolve_ticket, can_update_ticket_status, effective_role
from app.core.rate_limit import rate_limit
from app.core.exceptions import BadRequestError, InsufficientPermissionsError, NotFoundError
from app.core import cache as _cache
from app.core.config import settings
from app.db.session import get_db
from app.models.enums import TicketCategory, UserRole
from app.models.user import User
from app.schemas.ticket import (
    KnowledgeDraftPublishOut,
    TicketHistoryChange,
    TicketHistoryOut,
    TicketKnowledgeDraftOut,
    TicketOut,
    TicketPerformanceOut,
    TicketSimilarOut,
    TicketSimilarResponse,
    TicketStats,
    TicketStatusUpdate,
    TicketTriageUpdate,
)
from app.services.tickets import (
    compute_assignment_performance,
    compute_category_breakdown,
    compute_operational_insights,
    compute_problem_insights,
    compute_priority_breakdown,
    compute_type_breakdown,
    compute_stats,
    compute_weekly_trends,
    get_ticket,
    get_ticket_for_user,
    list_ticket_history_events,
    list_tickets_for_user,
    update_ticket_triage,
    update_status,
)
from app.services.problems import problem_analytics_summary
from app.services.ai.resolver import resolve_ticket_advice
from app.services.ai.routing_validation import validate_ticket_routing_for_ticket
from app.services.ai.similar_tickets import select_visible_similar_ticket_matches
from app.services.ticket_serialization import serialize_ticket_out

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])
_ALLOWED_SLA_STATUS_FILTERS = {"ok", "at_risk", "breached", "paused", "completed", "unknown"}
logger = logging.getLogger(__name__)


def _bust_ticket_analytics(user_id: str) -> None:
    for res in ("stats", "insights", "performance", "agent_perf"):
        _cache.delete_pattern(f"itsm:{res}:{user_id}*")


def _serialize_ticket(ticket) -> TicketOut:  # noqa: ANN001
    serialized, sanitized = serialize_ticket_out(ticket)
    if sanitized:
        logger.warning(
            "Sanitized malformed ticket payload before API response",
            extra={"ticket_id": serialized.id, "jira_key": getattr(ticket, "jira_key", None)},
        )
    return serialized


def _parse_history_changes(meta: dict | None) -> list[TicketHistoryChange]:
    if not isinstance(meta, dict):
        return []
    raw = meta.get("changes")
    if not isinstance(raw, list):
        return []
    changes: list[TicketHistoryChange] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        changes.append(
            TicketHistoryChange(
                field=field,
                before=item.get("before"),
                after=item.get("after"),
            )
        )
    return changes


def _to_ticket_history_out(event) -> TicketHistoryOut:
    meta = event.meta if isinstance(event.meta, dict) else {}
    return TicketHistoryOut(
        id=str(event.id),
        ticket_id=event.ticket_id,
        event_type=event.event_type,
        action=str(meta.get("action")) if meta.get("action") is not None else None,
        actor=event.actor,
        actor_id=str(meta.get("actor_id")) if meta.get("actor_id") is not None else None,
        actor_role=str(meta.get("actor_role")) if meta.get("actor_role") is not None else None,
        comment_added=bool(meta.get("comment_added", False)),
        comment_id=str(meta.get("comment_id")) if meta.get("comment_id") is not None else None,
        created_at=event.created_at,
        changes=_parse_history_changes(meta),
    )


@router.get("/", response_model=list[TicketOut])
def get_all_tickets(
    sla_status: str | None = Query(
        default=None,
        description="Filter by SLA status: ok|at_risk|breached|paused|completed|unknown",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketOut]:
    tickets = list_tickets_for_user(db, current_user)
    normalized_filter = sla_status.strip().lower() if isinstance(sla_status, str) and sla_status.strip() else None
    if normalized_filter:
        if normalized_filter not in _ALLOWED_SLA_STATUS_FILTERS:
            raise BadRequestError("invalid_sla_status_filter", details={"sla_status": sla_status})
        tickets = [
            ticket
            for ticket in tickets
            if str(ticket.sla_status or "unknown").strip().lower() == normalized_filter
        ]
    return [_serialize_ticket(ticket) for ticket in tickets]


@router.get("/stats", response_model=TicketStats)
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketStats:
    key = _cache.make_key("stats", str(current_user.id))
    hit = _cache.get(key)
    if hit is not None:
        return TicketStats(**hit)
    tickets = list_tickets_for_user(db, current_user)
    result = TicketStats(**compute_stats(tickets))
    _cache.set(key, result.model_dump(), ttl=settings.CACHE_TTL_STATS)
    return result


@router.get("/insights")
def get_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = _cache.make_key("insights", str(current_user.id))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    tickets = list_tickets_for_user(db, current_user)
    result = {
        "weekly": compute_weekly_trends(tickets),
        "ticket_type": compute_type_breakdown(tickets),
        "category": compute_category_breakdown(tickets),
        "priority": compute_priority_breakdown(tickets),
        "problems": compute_problem_insights(tickets),
        "problem_management": problem_analytics_summary(db),
        "operational": compute_operational_insights(tickets),
        "performance": compute_assignment_performance(tickets),
    }
    _cache.set(key, result, ttl=settings.CACHE_TTL_INSIGHTS)
    return result


@router.get("/performance", response_model=TicketPerformanceOut)
def get_performance_metrics(
    date_from: dt.date | None = Query(default=None),
    date_to: dt.date | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    assignee: str | None = Query(default=None, min_length=2, max_length=80),
    scope: Literal["all", "before", "after"] = Query(default="all"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketPerformanceOut:
    if date_from and date_to and date_from > date_to:
        raise BadRequestError("invalid_date_range")
    key = _cache.make_key("performance", str(current_user.id), {
        "date_from": str(date_from or ""),
        "date_to": str(date_to or ""),
        "category": str(category.value if category else ""),
        "assignee": str(assignee or ""),
        "scope": scope,
    })
    hit = _cache.get(key)
    if hit is not None:
        return TicketPerformanceOut(**hit)
    tickets = list_tickets_for_user(db, current_user)
    metrics = compute_assignment_performance(
        tickets,
        date_from=date_from,
        date_to=date_to,
        category=category,
        assignee=assignee,
        scope=scope,
    )
    result = TicketPerformanceOut(**metrics)
    _cache.set(key, result.model_dump(), ttl=settings.CACHE_TTL_PERFORMANCE)
    return result


@router.get("/history", response_model=list[TicketHistoryOut])
def get_ticket_history_feed(
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketHistoryOut]:
    if current_user.role != UserRole.admin:
        raise InsufficientPermissionsError("forbidden")
    events = list_ticket_history_events(db, limit=limit)
    return [_to_ticket_history_out(event) for event in events]


@router.get("/agent-performance")
def get_agent_performance(
    period_days: int = Query(default=30, ge=1, le=365),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Return per-agent performance metrics.

    Requires admin or agent role.

    Computes from tickets: tickets_assigned, tickets_resolved, mttr_hours,
    mttr_p90_hours, sla_breach_rate, avg_first_action_hours, open_ticket_count.

    Args:
        period_days: Look-back window in days (default 30).
        category: Optional ticket category filter.
        db: Database session.
        current_user: Authenticated user.

    Returns:
        Dict with period_days, agents list, generated_at.

    Raises:
        InsufficientPermissionsError: If current_user is not an admin or agent.
    """
    import statistics

    if current_user.role.value not in ("admin", "agent"):
        raise InsufficientPermissionsError("forbidden")

    key = _cache.make_key("agent_perf", str(current_user.id), {
        "period_days": period_days,
        "category": str(category or ""),
    })
    hit = _cache.get(key)
    if hit is not None:
        return hit

    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=period_days)

    tickets = list_tickets_for_user(db, current_user)

    # Filter by period and optional category
    period_tickets = [
        t
        for t in tickets
        if t.created_at
        and (
            t.created_at.replace(tzinfo=dt.timezone.utc)
            if t.created_at.tzinfo is None
            else t.created_at
        )
        >= since
        and (
            not category
            or str(getattr(t, "category", "") or "").lower() == category.lower()
        )
    ]

    # Group by assignee
    from collections import defaultdict

    by_agent: dict[str, list] = defaultdict(list)
    for t in period_tickets:
        assignee = str(getattr(t, "assignee", None) or "Unassigned").strip()
        by_agent[assignee].append(t)

    # Also include current open tickets (not filtered by period)
    open_statuses = {
        "open",
        "in_progress",
        "waiting_for_customer",
        "waiting_for_support_vendor",
        "pending",
    }
    all_open: dict[str, int] = defaultdict(int)
    for t in tickets:
        t_status = str(
            t.status.value if hasattr(t.status, "value") else getattr(t, "status", "") or ""
        ).lower()
        if t_status in open_statuses:
            assignee = str(getattr(t, "assignee", None) or "Unassigned").strip()
            all_open[assignee] += 1

    agents_out = []
    for agent_name, agent_tickets in by_agent.items():
        total = len(agent_tickets)
        resolved = [
            t
            for t in agent_tickets
            if str(
                t.status.value if hasattr(t.status, "value") else getattr(t, "status", "") or ""
            ).lower()
            in ("resolved", "closed")
        ]
        resolution_rate = round(len(resolved) / total, 4) if total else 0.0

        # MTTR
        mttr_values = []
        for t in resolved:
            resolved_at = getattr(t, "resolved_at", None)
            created_at = getattr(t, "created_at", None)
            if resolved_at and created_at:
                ra = (
                    resolved_at.replace(tzinfo=dt.timezone.utc)
                    if resolved_at.tzinfo is None
                    else resolved_at
                )
                ca = (
                    created_at.replace(tzinfo=dt.timezone.utc)
                    if created_at.tzinfo is None
                    else created_at
                )
                hours = (ra - ca).total_seconds() / 3600
                if hours >= 0:
                    mttr_values.append(hours)

        mttr_hours = round(statistics.mean(mttr_values), 2) if mttr_values else None
        mttr_p90 = None
        if len(mttr_values) >= 5:
            sorted_vals = sorted(mttr_values)
            p90_idx = int(len(sorted_vals) * 0.90)
            mttr_p90 = round(sorted_vals[min(p90_idx, len(sorted_vals) - 1)], 2)

        # SLA breach rate
        sla_tracked = [
            t
            for t in agent_tickets
            if getattr(t, "sla_resolution_due_at", None) or getattr(t, "due_at", None)
        ]
        sla_breached = [
            t
            for t in sla_tracked
            if str(getattr(t, "sla_status", "") or "").lower() == "breached"
        ]
        sla_breach_rate = (
            round(len(sla_breached) / len(sla_tracked), 4) if sla_tracked else None
        )

        # First action (first_action_at field if exists)
        fa_values = []
        for t in agent_tickets:
            fa = getattr(t, "first_action_at", None)
            ca = getattr(t, "created_at", None)
            if fa and ca:
                fa_utc = (
                    fa.replace(tzinfo=dt.timezone.utc) if fa.tzinfo is None else fa
                )
                ca_utc = (
                    ca.replace(tzinfo=dt.timezone.utc) if ca.tzinfo is None else ca
                )
                hours = (fa_utc - ca_utc).total_seconds() / 3600
                if hours >= 0:
                    fa_values.append(hours)
        avg_first_action = round(statistics.mean(fa_values), 2) if fa_values else None

        agents_out.append(
            {
                "agent_name": agent_name,
                "agent_email": None,
                "tickets_assigned": total,
                "tickets_resolved": len(resolved),
                "resolution_rate": resolution_rate,
                "mttr_hours": mttr_hours,
                "mttr_p90_hours": mttr_p90,
                "sla_breach_rate": sla_breach_rate,
                "avg_first_action_hours": avg_first_action,
                "open_ticket_count": all_open.get(agent_name, 0),
            }
        )

    # Sort by sla_breach_rate desc (None last)
    agents_out.sort(
        key=lambda a: -(a["sla_breach_rate"] if a["sla_breach_rate"] is not None else -1)
    )

    result = {
        "period_days": period_days,
        "agents": agents_out,
        "generated_at": now.isoformat(),
    }
    _cache.set(key, result, ttl=settings.CACHE_TTL_AGENT_PERF)
    return result


class _ClassifyDraftRequest(BaseModel):
    title: str = Field(..., min_length=10)
    description: str = Field(..., min_length=20)
    type: str = "incident"


class _CheckDuplicatesRequest(BaseModel):
    title: str
    description: str
    category: str | None = None


@router.post("/classify-draft")
async def classify_draft_ticket(
    payload: _ClassifyDraftRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Classify a draft ticket from title and description before creation.

    Requires agent or admin role.

    Returns:
        Dict with suggested_priority, suggested_category, suggested_assignee,
        confidence, confidence_band, reasoning.
    """
    from app.services.ai.classifier import classify_draft

    if current_user.role.value not in ("admin", "agent"):
        raise InsufficientPermissionsError("forbidden")
    result = await classify_draft(
        title=payload.title,
        description=payload.description,
        ticket_type=payload.type,
    )
    return result


@router.post("/check-duplicates")
async def check_duplicate_tickets(
    payload: _CheckDuplicatesRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Check for potential duplicate open tickets before creation.

    Requires agent or admin role.

    Returns:
        Dict with duplicates (list) and has_duplicates (bool).
        Returns {"duplicates": [], "has_duplicates": false} on any error.
    """
    from app.services.ai.duplicate_detection import detect_duplicate_tickets

    if current_user.role.value not in ("admin", "agent"):
        raise InsufficientPermissionsError("forbidden")
    try:
        candidates = await detect_duplicate_tickets(
            db=db,
            title=payload.title,
            description=payload.description,
            category=payload.category,
        )
        duplicates = [
            {
                "ticket_id": c.ticket_id,
                "title": c.title,
                "status": c.status,
                "assignee": c.assignee,
                "similarity_score": c.similarity_score,
                "match_reason": c.match_reason,
                "url": c.url,
            }
            for c in candidates
        ]
        return {"duplicates": duplicates, "has_duplicates": bool(duplicates)}
    except Exception:  # noqa: BLE001
        return {"duplicates": [], "has_duplicates": False}


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_by_id(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return _serialize_ticket(ticket)


@router.get("/{ticket_id}/similar", response_model=TicketSimilarResponse)
def get_similar_tickets(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    limit: int = Query(default=5, ge=1, le=12),
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketSimilarResponse:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    key = _cache.make_key("similar", str(current_user.id), {
        "ticket_id": ticket_id,
        "limit": limit,
        "min_score": min_score,
    })
    hit = _cache.get(key)
    if hit is not None:
        return TicketSimilarResponse.model_validate(hit)

    visible_tickets = list_tickets_for_user(db, current_user)
    resolver_output = resolve_ticket_advice(
        db,
        ticket,
        visible_tickets=visible_tickets,
        top_k=max(limit, 5),
        include_workflow=False,
    )
    matches: list[TicketSimilarOut] = []
    for match in select_visible_similar_ticket_matches(
        source_ticket=ticket,
        visible_tickets=visible_tickets,
        retrieval_rows=list((resolver_output.retrieval or {}).get("similar_tickets") or []),
        limit=limit,
        min_score=min_score,
    ):
        candidate = match["ticket"]
        similarity_score = float(match["similarity_score"] or 0.0)
        matches.append(
            TicketSimilarOut(
                id=candidate.id,
                title=candidate.title,
                description=candidate.description,
                status=candidate.status,
                priority=candidate.priority,
                ticket_type=candidate.ticket_type,
                category=candidate.category,
                assignee=candidate.assignee,
                reporter=candidate.reporter,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
                similarity_score=similarity_score,
            )
        )
    result = TicketSimilarResponse(
        ticket_id=ticket.id,
        matches=matches,
    )
    _cache.set(key, result.model_dump(), ttl=settings.CACHE_TTL_SIMILAR)
    return result


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryOut])
def get_ticket_history_by_id(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    limit: int = Query(default=120, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketHistoryOut]:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    if current_user.role != UserRole.admin:
        raise InsufficientPermissionsError("forbidden")
    events = list_ticket_history_events(db, ticket_id=ticket_id, limit=limit)
    return [_to_ticket_history_out(event) for event in events]


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket_status(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    payload: TicketStatusUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    if not can_update_ticket_status(
        current_user,
        ticket,
        new_status=payload.status.value,
        has_comment=bool((payload.comment or "").strip()),
    ):
        raise InsufficientPermissionsError("forbidden")
    try:
        ticket = update_status(
            db,
            ticket_id,
            payload.status,
            actor=current_user.name,
            actor_id=str(current_user.id),
            actor_role=current_user.role.value,
            resolution_comment=payload.comment,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))
    # Invalidate cached summary when status changes
    from app.services.ai.summarization import invalidate_ticket_summary
    invalidate_ticket_summary(ticket_id, db=db)
    _bust_ticket_analytics(str(current_user.id))
    return _serialize_ticket(ticket)


@router.patch("/{ticket_id}/triage", response_model=TicketOut)
def update_ticket_triage_data(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    payload: TicketTriageUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    if not can_edit_ticket_triage(current_user, ticket):
        raise InsufficientPermissionsError("forbidden")
    ticket = update_ticket_triage(
        db,
        ticket_id,
        payload,
        actor=current_user.name,
        actor_id=str(current_user.id),
        actor_role=current_user.role.value,
    )
    # Invalidate cached summary when triage fields change (description may be updated)
    from app.services.ai.summarization import invalidate_ticket_summary
    invalidate_ticket_summary(ticket_id, db=db)
    _bust_ticket_analytics(str(current_user.id))
    return _serialize_ticket(ticket)


@router.get("/{ticket_id}/summary")
async def get_ticket_summary(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    force_regenerate: bool = False,
    language: str = "fr",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get or generate an AI summary for a ticket.

    Returns cached summary if within TTL, otherwise generates a new one.

    Query params:
        force_regenerate: Bypass cache and regenerate.
        language: "fr" or "en" (default "fr").
    """
    from app.services.ai.summarization import generate_ticket_summary
    ticket_obj = get_ticket_for_user(db, ticket_id, current_user)
    if ticket_obj is None:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    ticket_dict = {
        "id": ticket_obj.id,
        "title": ticket_obj.title,
        "description": ticket_obj.description,
        "category": getattr(getattr(ticket_obj, "category", None), "value", str(getattr(ticket_obj, "category", "") or "")),
        "priority": getattr(getattr(ticket_obj, "priority", None), "value", str(getattr(ticket_obj, "priority", "") or "")),
        "status": getattr(getattr(ticket_obj, "status", None), "value", str(getattr(ticket_obj, "status", "") or "")),
        "assignee": ticket_obj.assignee,
        "reporter": ticket_obj.reporter,
        "ai_summary": getattr(ticket_obj, "ai_summary", None),
        "summary_generated_at": getattr(ticket_obj, "summary_generated_at", None),
    }
    result = await generate_ticket_summary(ticket_dict, db=db, force_regenerate=force_regenerate, language=language)
    return {
        "summary": result.summary,
        "similar_ticket_count": result.similar_ticket_count,
        "used_ticket_ids": result.used_ticket_ids,
        "generated_at": result.generated_at.isoformat(),
        "is_cached": result.is_cached,
        "language": result.language,
    }


@router.post("/{ticket_id}/resolution-suggestion")
async def get_resolution_suggestion(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Generate a suggested resolution text for a ticket being closed.

    Called when the agent opens the resolve dialog and the resolution
    field is empty. Returns a draft suggestion the agent can accept,
    edit, or ignore.

    Args:
        ticket_id: ID of the ticket being resolved.
        db: Database session.
        current_user: Authenticated user.

    Returns:
        Dict with suggestion (str), confidence (float),
        based_on_comments (bool), based_on_feedback (bool).

    Raises:
        NotFoundError: If ticket not found.
    """
    from app.services.ai.summarization import generate_resolution_suggestion
    from app.models.ticket import TicketComment

    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    # Load comments
    try:
        comments_raw = (
            db.query(TicketComment)
            .filter(TicketComment.ticket_id == ticket_id)
            .order_by(TicketComment.created_at.asc())
            .all()
        )
        comments = [
            {
                "body": c.content,
                "created_at": str(c.created_at),
                "author": getattr(c, "author", ""),
            }
            for c in comments_raw
        ]
    except Exception:  # noqa: BLE001
        comments = []

    ticket_dict = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "category": str(
            getattr(ticket.category, "value", ticket.category) if ticket.category else ""
        ),
        "priority": str(
            getattr(ticket.priority, "value", ticket.priority) if ticket.priority else ""
        ),
    }

    result = await generate_resolution_suggestion(ticket=ticket_dict, comments=comments)
    return {
        "suggestion": result.text,
        "confidence": result.confidence,
        "based_on_comments": result.based_on_comments,
        "based_on_feedback": result.based_on_feedback,
    }


@router.get("/{ticket_id}/knowledge-draft", response_model=TicketKnowledgeDraftOut)
def get_ticket_knowledge_draft_endpoint(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketKnowledgeDraftOut:
    """Return the persisted knowledge draft for a ticket, if one has been generated."""
    from app.models.knowledge_draft import KnowledgeDraft

    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    row = db.query(KnowledgeDraft).filter(KnowledgeDraft.ticket_id == ticket_id).first()
    if not row:
        raise NotFoundError("no_knowledge_draft", details={"ticket_id": ticket_id})

    return _knowledge_draft_row_to_out(row)


@router.post("/{ticket_id}/knowledge-draft", response_model=TicketKnowledgeDraftOut)
async def generate_ticket_knowledge_draft_endpoint(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    language: Literal["fr", "en"] = Query(default="fr"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketKnowledgeDraftOut:
    import uuid
    from app.models.knowledge_draft import KnowledgeDraft
    from app.models.ticket import TicketComment
    from app.services.ai.knowledge_drafts import generate_ticket_knowledge_draft

    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    normalized_status = str(getattr(ticket.status, "value", ticket.status) or "").lower()
    if normalized_status not in {"resolved", "closed"}:
        raise BadRequestError("ticket_must_be_resolved_for_kb_draft", details={"ticket_id": ticket_id})

    comments_raw = (
        db.query(TicketComment)
        .filter(TicketComment.ticket_id == ticket_id)
        .order_by(TicketComment.created_at.asc())
        .all()
    )
    comments = [
        {
            "body": comment.content,
            "created_at": str(comment.created_at),
            "author": getattr(comment, "author", ""),
        }
        for comment in comments_raw
    ]
    ticket_dict = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "category": str(getattr(ticket.category, "value", ticket.category) if ticket.category else ""),
        "priority": str(getattr(ticket.priority, "value", ticket.priority) if ticket.priority else ""),
        "status": normalized_status,
        "resolution": getattr(ticket, "resolution", None),
        "tags": list(getattr(ticket, "tags", []) or []),
    }
    draft = await generate_ticket_knowledge_draft(
        ticket=ticket_dict,
        comments=comments,
        lang=language,
    )

    # Persist (upsert by ticket_id — regenerating replaces the previous draft)
    existing = db.query(KnowledgeDraft).filter(KnowledgeDraft.ticket_id == ticket_id).first()
    if existing:
        existing.title = draft.title
        existing.summary = draft.summary
        existing.symptoms = draft.symptoms
        existing.root_cause = draft.root_cause
        existing.workaround = draft.workaround
        existing.resolution_steps = draft.resolution_steps
        existing.tags = draft.tags
        existing.review_note = draft.review_note
        existing.confidence = draft.confidence
        existing.source = draft.source
        existing.generated_at = draft.generated_at
        row = existing
    else:
        row = KnowledgeDraft(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            title=draft.title,
            summary=draft.summary,
            symptoms=draft.symptoms,
            root_cause=draft.root_cause,
            workaround=draft.workaround,
            resolution_steps=draft.resolution_steps,
            tags=draft.tags,
            review_note=draft.review_note,
            confidence=draft.confidence,
            source=draft.source,
            generated_at=draft.generated_at,
            created_by_user_id=str(current_user.id),
        )
        db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()

    return _knowledge_draft_row_to_out(row)


@router.post("/{ticket_id}/knowledge-draft/publish", response_model=KnowledgeDraftPublishOut)
async def publish_ticket_knowledge_draft_endpoint(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDraftPublishOut:
    """Publish a knowledge draft to the Confluence Knowledge Base and index it locally.

    Publish strategy (in priority order):
      1. Confluence KB  — if CONFLUENCE_SPACE_KEY is set, creates a native Confluence
         page in the JSM-linked space so it appears in the Knowledge Base sidebar.
      2. Jira issue fallback — if only Jira credentials are set (no space key), creates
         a labelled Jira issue in the KB project as a lightweight alternative.
      3. Local-only — if neither is configured, the draft is indexed in pgvector only
         (still available to the RAG chatbot, just not visible in Jira/Confluence).

    The endpoint is idempotent: a second call returns the already-published state.
    """
    import datetime as _dt
    from app.models.knowledge_draft import KnowledgeDraft

    row = db.query(KnowledgeDraft).filter(KnowledgeDraft.ticket_id == ticket_id).first()
    if not row:
        raise NotFoundError("no_knowledge_draft", details={"ticket_id": ticket_id})

    # Idempotent — return stored state without touching Confluence or Jira again.
    if row.published_at is not None:
        return KnowledgeDraftPublishOut(
            id=row.id,
            ticket_id=row.ticket_id,
            jira_issue_key=row.jira_issue_key,
            confluence_url=row.confluence_url if hasattr(row, "confluence_url") else None,
            published_at=row.published_at,
            kb_chunk_id=None,
        )

    jira_issue_key: str | None = None
    confluence_url: str | None = None

    from app.integrations.jira.client import JiraClient

    if settings.confluence_ready:
        # Primary path: create a native Confluence page in the JSM KB space.
        # The page appears immediately in the Knowledge Base sidebar.
        try:
            jira = JiraClient()
            body_html = _draft_to_confluence_html(row)
            result = jira.create_confluence_kb_article(
                space_key=settings.CONFLUENCE_SPACE_KEY.strip(),
                title=row.title,
                body_html=body_html,
                source_ticket_id=ticket_id,
            )
            jira_issue_key = result.get("id") or None   # Confluence page ID
            confluence_url = result.get("url") or None
        except Exception as exc:
            logger.warning("Confluence KB article creation failed for ticket %s: %s", ticket_id, exc)
            raise BadRequestError("confluence_kb_create_failed", details={"reason": str(exc)})

    elif settings.jira_ready:
        # Fallback: create a Jira issue when Confluence space key is not configured.
        try:
            jira = JiraClient()
            kb_project = (settings.JIRA_KB_ARTICLE_PROJECT_KEY or settings.JIRA_PROJECT_KEY).strip()
            body_text = _draft_to_text(row)
            result = jira.create_kb_article(kb_project, row.title, body_text, ticket_id)
            jira_issue_key = result.get("key") or None
        except Exception as exc:
            logger.warning("Jira KB article creation failed for ticket %s: %s", ticket_id, exc)
            raise BadRequestError("jira_kb_create_failed", details={"reason": str(exc)})

    # Always index locally so the RAG chatbot can search this article immediately.
    kb_chunk_id: int | None = None
    try:
        kb_chunk_id = _insert_kb_chunk_for_draft(db, row, jira_issue_key)
    except Exception as exc:
        logger.warning("KB chunk insert failed for ticket %s: %s", ticket_id, exc)

    # Persist publish state.
    now = _dt.datetime.now(_dt.timezone.utc)
    row.published_at = now
    row.jira_issue_key = jira_issue_key
    if hasattr(row, "confluence_url"):
        row.confluence_url = confluence_url
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()

    return KnowledgeDraftPublishOut(
        id=row.id,
        ticket_id=row.ticket_id,
        jira_issue_key=jira_issue_key,
        confluence_url=confluence_url,
        published_at=now,
        kb_chunk_id=kb_chunk_id,
    )


# ---------------------------------------------------------------------------
# Knowledge draft helpers
# ---------------------------------------------------------------------------

def _knowledge_draft_row_to_out(row: "KnowledgeDraft") -> TicketKnowledgeDraftOut:  # type: ignore[name-defined]
    from app.models.knowledge_draft import KnowledgeDraft  # noqa: F401
    status = "published" if row.published_at is not None else "draft"
    return TicketKnowledgeDraftOut(
        id=row.id,
        ticket_id=row.ticket_id,
        title=row.title,
        summary=row.summary,
        symptoms=row.symptoms or [],
        root_cause=row.root_cause,
        confluence_url=getattr(row, "confluence_url", None),
        workaround=row.workaround,
        resolution_steps=row.resolution_steps or [],
        tags=row.tags or [],
        review_note=row.review_note,
        confidence=row.confidence,
        source=row.source,
        generated_at=row.generated_at,
        published_at=row.published_at,
        jira_issue_key=row.jira_issue_key,
        status=status,
    )


def _draft_to_text(row: "KnowledgeDraft") -> str:  # type: ignore[name-defined]
    """Format draft fields into readable plain-text for the Jira issue body."""
    parts: list[str] = [f"Title: {row.title}", f"\nSummary:\n{row.summary}"]
    if row.symptoms:
        parts.append("\nSymptoms:\n" + "\n".join(f"- {s}" for s in row.symptoms))
    if row.root_cause:
        parts.append(f"\nRoot Cause:\n{row.root_cause}")
    if row.workaround:
        parts.append(f"\nWorkaround:\n{row.workaround}")
    if row.resolution_steps:
        steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(row.resolution_steps))
        parts.append(f"\nResolution Steps:\n{steps}")
    if row.tags:
        parts.append("\nTags: " + ", ".join(row.tags))
    parts.append(f"\n---\nSource ticket: {row.ticket_id}")
    return "\n".join(parts)


def _esc(text: str) -> str:
    """Minimal XML escaping for Confluence storage format."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _draft_to_confluence_html(row: "KnowledgeDraft") -> str:  # type: ignore[name-defined]
    """Render a KnowledgeDraft as Confluence storage-format HTML.

    Confluence storage format is a subset of XHTML. This function produces
    well-structured content with semantic headings, lists, and an info panel
    that shows confidence and source ticket — visible directly in the JSM KB sidebar.
    """
    html: list[str] = []

    html.append(f"<h2>Summary</h2><p>{_esc(row.summary)}</p>")

    if row.symptoms:
        items = "".join(f"<li>{_esc(s)}</li>" for s in row.symptoms)
        html.append(f"<h2>Symptoms</h2><ul>{items}</ul>")

    if row.root_cause:
        html.append(f"<h2>Root Cause</h2><p>{_esc(row.root_cause)}</p>")

    if row.workaround:
        html.append(f"<h2>Workaround</h2><p>{_esc(row.workaround)}</p>")

    if row.resolution_steps:
        items = "".join(f"<li>{_esc(s)}</li>" for s in row.resolution_steps)
        html.append(f"<h2>Resolution Steps</h2><ol>{items}</ol>")

    if row.tags:
        tag_list = ", ".join(_esc(t) for t in row.tags)
        html.append(f"<p><strong>Tags:</strong> {tag_list}</p>")

    confidence_pct = f"{int(row.confidence * 100)}%" if row.confidence else "N/A"
    html.append(
        f'<ac:structured-macro ac:name="info">'
        f"<ac:rich-text-body>"
        f"<p>Source ticket: <strong>{_esc(row.ticket_id)}</strong> &nbsp;|&nbsp; "
        f"AI confidence: <strong>{confidence_pct}</strong></p>"
        f"</ac:rich-text-body>"
        f"</ac:structured-macro>"
    )

    return "".join(html)


def _insert_kb_chunk_for_draft(db: "Session", row: "KnowledgeDraft", jira_key: str | None) -> int | None:  # type: ignore[name-defined]
    """Embed the draft and insert a KBChunk for immediate RAG availability."""
    import hashlib
    try:
        from app.models.kb_chunk import KBChunk
        from app.services.embeddings import compute_embedding
    except Exception:
        return None

    content = _draft_to_text(row)
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:64]

    existing_chunk = db.query(KBChunk).filter(KBChunk.content_hash == content_hash).first()
    if existing_chunk:
        return existing_chunk.id

    try:
        embedding = compute_embedding(content)
    except Exception as exc:
        logger.warning("Embedding failed for knowledge draft %s: %s", row.id, exc)
        embedding = None

    chunk = KBChunk(
        source_type="local_kb_draft",
        jira_issue_id=None,
        jira_key=jira_key,
        comment_id=None,
        content=content,
        content_hash=content_hash,
        metadata_json={
            "source_ticket_id": row.ticket_id,
            "title": row.title,
            "source": row.source,
            "confidence": row.confidence,
            "tags": row.tags or [],
        },
        embedding=embedding,
    )
    db.add(chunk)
    db.flush()
    return chunk.id
