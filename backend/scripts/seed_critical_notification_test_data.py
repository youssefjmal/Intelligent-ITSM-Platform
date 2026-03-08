"""Seed critical test tickets and notifications for bell/notification-center QA."""

from __future__ import annotations

import datetime as dt

from app.db.session import SessionLocal
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.models.user import User


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _upsert_ticket(db, payload: dict, *, assignee: str, reporter: str) -> Ticket:
    ticket = db.get(Ticket, payload["id"])
    if ticket is None:
        ticket = Ticket(
            id=payload["id"],
            title=payload["title"],
            description=payload["description"],
            status=TicketStatus.open,
            priority=TicketPriority.critical,
            category=payload["category"],
            assignee=assignee,
            reporter=reporter,
            tags=["critical", "qa-seed", payload["category"].value],
            source="local",
        )
        db.add(ticket)
    else:
        ticket.title = payload["title"]
        ticket.description = payload["description"]
        ticket.status = TicketStatus.open
        ticket.priority = TicketPriority.critical
        ticket.category = payload["category"]
        ticket.assignee = assignee
        ticket.reporter = reporter
        ticket.tags = ["critical", "qa-seed", payload["category"].value]
        ticket.updated_at = _utcnow()
    db.flush()
    return ticket


def _add_notification(db, *, user: User, ticket: Ticket, body: str) -> None:
    db.add(
        Notification(
            user_id=user.id,
            title=f"Critical ticket detected: {ticket.id}",
            body=body,
            severity="critical",
            link=f"/tickets/{ticket.id}",
            source="n8n",
            created_at=_utcnow(),
        )
    )


def run() -> None:
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.asc()).all()
        if not users:
            print("No users found. Seed users first.")
            return

        admin = next((u for u in users if u.role == UserRole.admin), users[0])
        agent = next((u for u in users if u.role == UserRole.agent), admin)

        tickets_payload = [
            {
                "id": "TW-9101",
                "title": "Core switch loop detected in HQ network",
                "description": (
                    "Intermittent outage impacting Floor 2 and Floor 3. "
                    "Packet loss > 40% observed after topology update. "
                    "Urgent rollback and loop-guard verification required."
                ),
                "category": TicketCategory.network,
            },
            {
                "id": "TW-9102",
                "title": "Production VM datastore latency spike",
                "description": (
                    "Datastore latency increased to 180ms, causing API timeouts for billing service. "
                    "Storage path failover appears degraded; investigate host adapter + SAN health."
                ),
                "category": TicketCategory.infrastructure,
            },
            {
                "id": "TW-9103",
                "title": "Critical hardware failure: floor 3 label printer controller board",
                "description": (
                    "Warehouse label printer on Floor 3 fails POST with controller fault code E-47. "
                    "Shipment labels cannot be printed. Replacement board and temporary fallback device required."
                ),
                "category": TicketCategory.hardware,
            },
            {
                "id": "TW-9104",
                "title": "Admin account lockout wave after MFA policy push",
                "description": (
                    "Multiple privileged users locked out after conditional access change. "
                    "Audit indicates token claim mismatch for legacy app gateway."
                ),
                "category": TicketCategory.security,
            },
            {
                "id": "TW-9105",
                "title": "Customer portal checkout returns 500 for premium plan",
                "description": (
                    "Checkout endpoint throws 500 for premium subscriptions only. "
                    "Rollback candidate: payment-tax rule engine release 2026.03.03."
                ),
                "category": TicketCategory.application,
            },
        ]

        seeded_tickets: list[Ticket] = []
        for item in tickets_payload:
            seeded_tickets.append(
                _upsert_ticket(
                    db,
                    item,
                    assignee=agent.name,
                    reporter=admin.name,
                )
            )

        for user in users:
            for ticket in seeded_tickets:
                detail = (
                    f"{ticket.title}. "
                    f"Category: {ticket.category.value}. "
                    f"Priority: critical. "
                    f"Assignee: {ticket.assignee}. "
                    "Automation source: n8n test payload for notification center hover/click validation."
                )
                _add_notification(db, user=user, ticket=ticket, body=detail)

        db.commit()
        print(f"Seeded {len(seeded_tickets)} critical tickets and {len(users) * len(seeded_tickets)} notifications.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()

