"""Seed mailing-related tickets and trigger problem linking/detection."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import TicketCategory, TicketPriority, TicketStatus  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.services.problems import detect_problems, link_ticket_to_problem  # noqa: E402


MAILING_TICKETS = [
    {
        "id": "TW-M9001",
        "title": "Outbound payroll mails queued for hours",
        "description": "Dispatch pipeline retries continuously and employees do not receive salary notifications.",
        "tags": ["dispatch", "payroll"],
    },
    {
        "id": "TW-M9002",
        "title": "Outbox delivery frozen after relay certificate update",
        "description": "Mail transport is stuck in deferred mode and queued sends never clear.",
        "tags": ["transport", "certificate"],
    },
    {
        "id": "TW-M9003",
        "title": "SMTP handoff times out for customer confirmations",
        "description": "Gateway accepts connection but message transfer stalls until retry limit is reached.",
        "tags": ["smtp", "handoff"],
    },
    {
        "id": "TW-M9004",
        "title": "Confirmation emails remain pending in send buffer",
        "description": "Mail flow backlog grows while retry workers cycle without successful submission.",
        "tags": ["buffer", "notifications"],
    },
    {
        "id": "TW-M9005",
        "title": "Transactional email pipeline defers all outbound traffic",
        "description": "Outgoing messages stay in queue and no recipients get completion notices.",
        "tags": ["pipeline", "outbound"],
    },
]


def seed() -> None:
    db = SessionLocal()
    now = dt.datetime.now(dt.timezone.utc)
    inserted = 0
    linked = 0

    try:
        for index, payload in enumerate(MAILING_TICKETS):
            ticket = db.query(Ticket).filter(Ticket.id == payload["id"]).first()
            if ticket is None:
                created_at = now - dt.timedelta(hours=(len(MAILING_TICKETS) - index))
                ticket = Ticket(
                    id=payload["id"],
                    title=payload["title"],
                    description=payload["description"],
                    status=TicketStatus.open,
                    priority=TicketPriority.high,
                    category=TicketCategory.email,
                    assignee="Yassine Trabelsi",
                    reporter="Mail Ops",
                    created_at=created_at,
                    updated_at=created_at,
                    tags=payload["tags"],
                )
                db.add(ticket)
                db.flush()
                inserted += 1

            before = ticket.problem_id
            linked_problem = link_ticket_to_problem(db, ticket)
            if linked_problem is not None and ticket.problem_id and ticket.problem_id != before:
                linked += 1

        db.commit()
        detect_result = detect_problems(db, window_days=30, min_count=5)
        db.commit()

        rows = db.query(Ticket).filter(Ticket.id.in_([item["id"] for item in MAILING_TICKETS])).order_by(Ticket.id.asc()).all()
        print(f"inserted={inserted}")
        print(f"newly_linked={linked}")
        print(
            "detect_result="
            f"processed_groups={detect_result['processed_groups']} created={detect_result['created']} "
            f"updated={detect_result['updated']} linked={detect_result['linked']}"
        )
        for ticket in rows:
            print(f"{ticket.id}\tproblem_id={ticket.problem_id}\tstatus={ticket.status.value}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
