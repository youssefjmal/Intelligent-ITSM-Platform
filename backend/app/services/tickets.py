"""Service helpers for ticket CRUD and analytics."""

from __future__ import annotations

import datetime as dt
from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.schemas.ticket import TicketCreate


def list_tickets(db: Session) -> list[Ticket]:
    return db.query(Ticket).order_by(Ticket.created_at.desc()).all()


def get_ticket(db: Session, ticket_id: str) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def _next_ticket_id(db: Session) -> str:
    ids = [t[0] for t in db.query(Ticket.id).all()]
    max_num = 1000
    for tid in ids:
        try:
            num = int(tid.split("-")[-1])
            max_num = max(max_num, num)
        except ValueError:
            continue
    return f"TW-{max_num + 1}"


def create_ticket(db: Session, data: TicketCreate) -> Ticket:
    now = dt.datetime.now(dt.timezone.utc)
    ticket = Ticket(
        id=_next_ticket_id(db),
        title=data.title,
        description=data.description,
        priority=data.priority,
        category=data.category,
        assignee=data.assignee,
        reporter=data.reporter,
        status=TicketStatus.open,
        created_at=now,
        updated_at=now,
        tags=data.tags,
        comments=[],
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_status(db: Session, ticket_id: str, status: TicketStatus) -> Ticket | None:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        return None
    ticket.status = status
    ticket.updated_at = dt.datetime.now(dt.timezone.utc)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def compute_stats(tickets: list[Ticket]) -> dict:
    total = len(tickets)
    open_count = sum(1 for t in tickets if t.status == TicketStatus.open)
    in_progress = sum(1 for t in tickets if t.status == TicketStatus.in_progress)
    pending = sum(1 for t in tickets if t.status == TicketStatus.pending)
    resolved = sum(1 for t in tickets if t.status == TicketStatus.resolved)
    closed = sum(1 for t in tickets if t.status == TicketStatus.closed)
    critical = sum(1 for t in tickets if t.priority == TicketPriority.critical)
    high = sum(1 for t in tickets if t.priority == TicketPriority.high)

    resolved_tickets = [t for t in tickets if t.status in {TicketStatus.resolved, TicketStatus.closed}]
    if resolved_tickets:
        days = [
            max((t.updated_at - t.created_at).total_seconds() / 86400, 0)
            for t in resolved_tickets
        ]
        avg_resolution = round(sum(days) / len(days), 2)
    else:
        avg_resolution = 0.0

    resolution_rate = round(((resolved + closed) / total) * 100) if total else 0

    return {
        "total": total,
        "open": open_count,
        "in_progress": in_progress,
        "pending": pending,
        "resolved": resolved,
        "closed": closed,
        "critical": critical,
        "high": high,
        "resolution_rate": resolution_rate,
        "avg_resolution_days": avg_resolution,
    }


def compute_category_breakdown(tickets: list[Ticket]) -> list[dict]:
    categories = [
        TicketCategory.bug,
        TicketCategory.feature,
        TicketCategory.support,
        TicketCategory.infrastructure,
        TicketCategory.security,
    ]
    labels = {
        TicketCategory.bug: "Bug",
        TicketCategory.feature: "Fonctionnalite",
        TicketCategory.support: "Support",
        TicketCategory.infrastructure: "Infrastructure",
        TicketCategory.security: "Securite",
    }
    return [
        {"category": labels[c], "count": sum(1 for t in tickets if t.category == c)}
        for c in categories
    ]


def compute_priority_breakdown(tickets: list[Ticket]) -> list[dict]:
    priorities = [
        TicketPriority.critical,
        TicketPriority.high,
        TicketPriority.medium,
        TicketPriority.low,
    ]
    labels = {
        TicketPriority.critical: "Critique",
        TicketPriority.high: "Haute",
        TicketPriority.medium: "Moyenne",
        TicketPriority.low: "Basse",
    }
    colors = {
        TicketPriority.critical: "#dc2626",
        TicketPriority.high: "#f59e0b",
        TicketPriority.medium: "#2e9461",
        TicketPriority.low: "#64748b",
    }
    return [
        {
            "priority": labels[p],
            "count": sum(1 for t in tickets if t.priority == p),
            "fill": colors[p],
        }
        for p in priorities
    ]


def compute_weekly_trends(tickets: list[Ticket], weeks: int = 6) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    buckets = []
    for i in range(weeks):
        start = (now - dt.timedelta(weeks=weeks - i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(weeks=1)
        opened = sum(1 for t in tickets if start <= t.created_at < end)
        closed = sum(1 for t in tickets if t.status in {TicketStatus.closed, TicketStatus.resolved} and start <= t.updated_at < end)
        pending = sum(1 for t in tickets if t.status == TicketStatus.pending and start <= t.updated_at < end)
        buckets.append({"week": f"Sem {i + 1}", "opened": opened, "closed": closed, "pending": pending})
    return buckets
