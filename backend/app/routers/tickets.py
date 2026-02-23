"""Ticket CRUD endpoints and analytics."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Body, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rbac import can_edit_ticket_triage, can_resolve_ticket
from app.core.rate_limit import rate_limit
from app.core.exceptions import BadRequestError, InsufficientPermissionsError, NotFoundError
from app.db.session import get_db
from app.models.enums import TicketCategory
from app.models.user import User
from app.schemas.ticket import (
    TicketCreate,
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
    compute_stats,
    compute_weekly_trends,
    create_ticket,
    get_ticket,
    get_ticket_for_user,
    list_tickets,
    list_tickets_for_user,
    update_ticket_triage,
    update_status,
)
from app.services.problems import problem_analytics_summary
from app.services.problems import find_similar_tickets

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])
_ALLOWED_SLA_STATUS_FILTERS = {"ok", "at_risk", "breached", "paused", "completed", "unknown"}


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
    if sla_status:
        normalized = sla_status.strip().lower()
        if normalized not in _ALLOWED_SLA_STATUS_FILTERS:
            raise BadRequestError("invalid_sla_status_filter", details={"sla_status": sla_status})
        tickets = [ticket for ticket in tickets if str(ticket.sla_status or "unknown").strip().lower() == normalized]
    return [TicketOut.model_validate(t) for t in tickets]


@router.get("/stats", response_model=TicketStats)
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketStats:
    tickets = list_tickets_for_user(db, current_user)
    return TicketStats(**compute_stats(tickets))


@router.get("/insights")
def get_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tickets = list_tickets_for_user(db, current_user)
    return {
        "weekly": compute_weekly_trends(tickets),
        "category": compute_category_breakdown(tickets),
        "priority": compute_priority_breakdown(tickets),
        "problems": compute_problem_insights(tickets),
        "problem_management": problem_analytics_summary(db),
        "operational": compute_operational_insights(tickets),
        "performance": compute_assignment_performance(tickets),
    }


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
    tickets = list_tickets_for_user(db, current_user)
    metrics = compute_assignment_performance(
        tickets,
        date_from=date_from,
        date_to=date_to,
        category=category,
        assignee=assignee,
        scope=scope,
    )
    return TicketPerformanceOut(**metrics)


@router.post("/", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_new_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    payload.reporter = current_user.name
    ticket = create_ticket(db, payload, reporter_id=str(current_user.id))
    return TicketOut.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_by_id(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return TicketOut.model_validate(ticket)


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

    visible_tickets = list_tickets_for_user(db, current_user)
    matches = find_similar_tickets(
        ticket=ticket,
        candidates=visible_tickets,
        limit=limit,
        min_score=min_score,
    )
    return TicketSimilarResponse(
        ticket_id=ticket.id,
        matches=[
            TicketSimilarOut(
                id=item.id,
                title=item.title,
                description=item.description,
                status=item.status,
                priority=item.priority,
                category=item.category,
                assignee=item.assignee,
                reporter=item.reporter,
                created_at=item.created_at,
                updated_at=item.updated_at,
                similarity_score=round(float(score), 4),
            )
            for item, score in matches
        ],
    )


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
    if not can_resolve_ticket(current_user, ticket):
        raise InsufficientPermissionsError("forbidden")
    try:
        ticket = update_status(
            db,
            ticket_id,
            payload.status,
            actor=current_user.name,
            resolution_comment=payload.comment,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return TicketOut.model_validate(ticket)


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
    )
    return TicketOut.model_validate(ticket)
