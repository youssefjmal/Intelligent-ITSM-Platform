"""Ticket CRUD endpoints and analytics."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Body, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core.exceptions import BadRequestError, InsufficientPermissionsError, NotFoundError
from app.db.session import get_db
from app.models.enums import TicketCategory, UserRole
from app.models.user import User
from app.schemas.ticket import (
    TicketCreate,
    TicketOut,
    TicketPerformanceOut,
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
    list_tickets,
    update_ticket_triage,
    update_status,
)

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])


@router.get("/", response_model=list[TicketOut])
def get_all_tickets(db: Session = Depends(get_db)) -> list[TicketOut]:
    return [TicketOut.model_validate(t) for t in list_tickets(db)]


@router.get("/stats", response_model=TicketStats)
def get_stats(db: Session = Depends(get_db)) -> TicketStats:
    tickets = list_tickets(db)
    return TicketStats(**compute_stats(tickets))


@router.get("/insights")
def get_insights(db: Session = Depends(get_db)) -> dict:
    tickets = list_tickets(db)
    return {
        "weekly": compute_weekly_trends(tickets),
        "category": compute_category_breakdown(tickets),
        "priority": compute_priority_breakdown(tickets),
        "problems": compute_problem_insights(tickets),
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
) -> TicketPerformanceOut:
    if date_from and date_to and date_from > date_to:
        raise BadRequestError("invalid_date_range")
    tickets = list_tickets(db)
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
def create_new_ticket(payload: TicketCreate, db: Session = Depends(get_db)) -> TicketOut:
    ticket = create_ticket(db, payload)
    return TicketOut.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_by_id(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return TicketOut.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket_status(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    payload: TicketStatusUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
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
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return TicketOut.model_validate(ticket)


@router.patch("/{ticket_id}/triage", response_model=TicketOut)
def update_ticket_triage_data(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    payload: TicketTriageUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketOut:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
        raise InsufficientPermissionsError("forbidden")
    ticket = update_ticket_triage(
        db,
        ticket_id,
        payload,
        actor=current_user.name,
    )
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return TicketOut.model_validate(ticket)
