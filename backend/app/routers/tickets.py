"""Ticket CRUD endpoints and analytics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.schemas.ticket import TicketCreate, TicketOut, TicketStats, TicketStatusUpdate
from app.services.tickets import (
    compute_category_breakdown,
    compute_priority_breakdown,
    compute_stats,
    compute_weekly_trends,
    create_ticket,
    get_ticket,
    list_tickets,
    update_status,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


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
    }


@router.post("/", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_new_ticket(payload: TicketCreate, db: Session = Depends(get_db)) -> TicketOut:
    ticket = create_ticket(db, payload)
    return TicketOut.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket_by_id(ticket_id: str, db: Session = Depends(get_db)) -> TicketOut:
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ticket_not_found")
    return TicketOut.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = update_status(db, ticket_id, payload.status)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ticket_not_found")
    return TicketOut.model_validate(ticket)
