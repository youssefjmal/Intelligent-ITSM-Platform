"""Seed one deterministic demo ticket that exercises the real notification flow.

This script is meant for local QA and demos:
- creates or refreshes a single ticket and linked problem
- emits notifications through the notification service helpers
- proves bell unread counts, notifications page items, and delivery audit events
"""

from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, select

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProblemStatus, TicketCategory, TicketPriority, TicketStatus, TicketType, UserRole  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.notifications_service import (  # noqa: E402
    EVENT_SYSTEM_ALERT,
    create_notifications_for_users,
    notify_ticket_assignment_change,
    notify_ticket_comment,
    notify_ticket_problem_link,
    notify_ticket_status_change,
)

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)

TICKET_ID = "TW-DEMO-NOTIFY-01"
PROBLEM_ID = "PB-DEMO-NOTIFY-01"
COMMENT_ONE_ID = "ND-C-001"
COMMENT_TWO_ID = "ND-C-002"
TICKET_LINK = f"/tickets/{TICKET_ID}"


def _pick_user(users: list[User], *, role: UserRole | None = None, exclude_ids: set[str] | None = None) -> User | None:
    excluded = exclude_ids or set()
    for user in users:
        if str(user.id) in excluded:
            continue
        if role is None or user.role == role:
            return user
    return None


def _dedupe_users(*users: User) -> list[User]:
    unique: list[User] = []
    seen: set[str] = set()
    for user in users:
        key = str(user.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(user)
    return unique


def _upsert_problem(db, *, title: str) -> Problem:
    problem = db.get(Problem, PROBLEM_ID)
    if problem is None:
        problem = Problem(
            id=PROBLEM_ID,
            title=title,
            category=TicketCategory.email,
            status=ProblemStatus.known_error,
            root_cause="Connector rotation left the shared mailbox forwarding rule bound to the old identity.",
            workaround="Temporarily resend important updates manually while validating the shared mailbox connector identity.",
            permanent_fix="Rebuild the forwarding rule using the current connector identity and reauthorize the Teams destination.",
            similarity_key="demo|notifications|mail-forwarding",
            created_at=NOW - dt.timedelta(hours=2),
            updated_at=NOW - dt.timedelta(minutes=20),
            last_seen_at=NOW - dt.timedelta(minutes=20),
        )
        db.add(problem)
    else:
        problem.title = title
        problem.category = TicketCategory.email
        problem.status = ProblemStatus.known_error
        problem.root_cause = "Connector rotation left the shared mailbox forwarding rule bound to the old identity."
        problem.workaround = "Temporarily resend important updates manually while validating the shared mailbox connector identity."
        problem.permanent_fix = "Rebuild the forwarding rule using the current connector identity and reauthorize the Teams destination."
        problem.similarity_key = "demo|notifications|mail-forwarding"
        problem.updated_at = NOW - dt.timedelta(minutes=20)
        problem.last_seen_at = NOW - dt.timedelta(minutes=20)
    db.flush()
    return problem


def _upsert_ticket(db, *, reporter: User, initial_assignee: User) -> Ticket:
    ticket = db.get(Ticket, TICKET_ID)
    if ticket is None:
        ticket = Ticket(
            id=TICKET_ID,
            title="Demo notification ticket: shared mailbox forwarding stopped",
            description=(
                "Local QA ticket seeded through the real notification helpers. "
                "The shared mailbox still receives messages, but forwarding to Teams stopped after connector rotation."
            ),
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            ticket_type=TicketType.incident,
            category=TicketCategory.email,
            assignee=initial_assignee.name,
            reporter=reporter.name,
            reporter_id=str(reporter.id),
            source="local",
            tags=["demo", "notifications", "mail-forwarding"],
            created_at=NOW - dt.timedelta(hours=1, minutes=30),
            updated_at=NOW - dt.timedelta(hours=1, minutes=30),
        )
        db.add(ticket)
    else:
        ticket.title = "Demo notification ticket: shared mailbox forwarding stopped"
        ticket.description = (
            "Local QA ticket seeded through the real notification helpers. "
            "The shared mailbox still receives messages, but forwarding to Teams stopped after connector rotation."
        )
        ticket.status = TicketStatus.open
        ticket.priority = TicketPriority.medium
        ticket.ticket_type = TicketType.incident
        ticket.category = TicketCategory.email
        ticket.assignee = initial_assignee.name
        ticket.reporter = reporter.name
        ticket.reporter_id = str(reporter.id)
        ticket.problem_id = None
        ticket.resolution = None
        ticket.source = "local"
        ticket.tags = ["demo", "notifications", "mail-forwarding"]
        ticket.updated_at = NOW - dt.timedelta(hours=1, minutes=30)
    db.flush()
    return ticket


def _reset_demo_state(db) -> None:
    db.execute(delete(Notification).where(Notification.link == TICKET_LINK))
    db.execute(delete(TicketComment).where(TicketComment.ticket_id == TICKET_ID))
    db.flush()


def _add_comment(db, *, ticket: Ticket, comment_id: str, author: str, content: str, created_at: dt.datetime) -> TicketComment:
    comment = TicketComment(
        id=comment_id,
        ticket_id=ticket.id,
        author=author,
        content=content,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(comment)
    db.flush()
    return comment


def run() -> None:
    db = SessionLocal()
    try:
        users = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
        if not users:
            print("No users found. Run the standard seed first, then rerun this demo.")
            return

        admin = _pick_user(users, role=UserRole.admin) or users[0]
        primary_agent = _pick_user(users, role=UserRole.agent, exclude_ids={str(admin.id)}) or admin

        problem = _upsert_problem(db, title="Demo problem: mailbox connector forwarding stops after rotation")
        ticket = _upsert_ticket(db, reporter=admin, initial_assignee=admin)
        _reset_demo_state(db)

        created_notifications: list[Notification] = []

        created_notifications.extend(
            notify_ticket_assignment_change(
                db,
                ticket=ticket,
                previous_assignee=None,
                actor="Notification Demo Seeder",
                notify_previous_assignee=False,
            )
        )

        if primary_agent.id != admin.id:
            previous_assignee = ticket.assignee
            ticket.assignee = primary_agent.name
            ticket.updated_at = NOW - dt.timedelta(minutes=55)
            db.flush()
            created_notifications.extend(
                notify_ticket_assignment_change(
                    db,
                    ticket=ticket,
                    previous_assignee=previous_assignee,
                    actor=admin.name,
                    notify_previous_assignee=True,
                )
            )

        comment_one = _add_comment(
            db,
            ticket=ticket,
            comment_id=COMMENT_ONE_ID,
            author=primary_agent.name,
            content=(
                "Initial triage is complete. "
                f"@{admin.email} can you confirm the connector rotation window before we rebuild the forwarding rule?"
            ),
            created_at=NOW - dt.timedelta(minutes=45),
        )
        created_notifications.extend(
            notify_ticket_comment(
                db,
                ticket=ticket,
                comment_text=comment_one.content,
                comment_id=comment_one.id,
                actor=primary_agent.name,
            )
        )

        comment_two = _add_comment(
            db,
            ticket=ticket,
            comment_id=COMMENT_TWO_ID,
            author=admin.name,
            content=(
                "Connector rotation is confirmed. "
                f"@{primary_agent.email} please rebuild the forwarding rule and validate Teams delivery after the change."
            ),
            created_at=NOW - dt.timedelta(minutes=32),
        )
        created_notifications.extend(
            notify_ticket_comment(
                db,
                ticket=ticket,
                comment_text=comment_two.content,
                comment_id=comment_two.id,
                actor=admin.name,
            )
        )

        previous_status = ticket.status.value
        ticket.status = TicketStatus.in_progress
        ticket.problem_id = problem.id
        ticket.updated_at = NOW - dt.timedelta(minutes=25)
        db.flush()
        created_notifications.extend(
            notify_ticket_status_change(
                db,
                ticket=ticket,
                previous_status=previous_status,
                actor=admin.name,
            )
        )
        created_notifications.extend(
            notify_ticket_problem_link(
                db,
                ticket=ticket,
                problem_id=problem.id,
            )
        )

        created_notifications.extend(
            create_notifications_for_users(
                db,
                users=_dedupe_users(admin, primary_agent),
                title=f"Demo critical alert: {ticket.id}",
                body="Pinned demo alert to validate critical bell styling and read-state behavior.",
                severity="critical",
                link=TICKET_LINK,
                source="system",
                cooldown_minutes=20,
                metadata_json={
                    "ticket_id": ticket.id,
                    "ticket_title": ticket.title,
                    "demo": True,
                },
                action_type="view",
                action_payload={"ticket_id": ticket.id},
                event_type=EVENT_SYSTEM_ALERT,
                pinned_until_read=True,
            )
        )

        db.commit()

        demo_rows = db.execute(
            select(Notification).where(Notification.link == TICKET_LINK).order_by(Notification.created_at.asc())
        ).scalars().all()

        by_user: dict[str, list[str]] = defaultdict(list)
        for row in demo_rows:
            user = db.get(User, row.user_id)
            label = f"{row.event_type}:{row.severity}"
            if row.pinned_until_read:
                label = f"{label}:pinned"
            by_user[user.name if user else str(row.user_id)].append(label)

        print(f"Seeded demo ticket {ticket.id} and linked problem {problem.id}.")
        print(f"Ticket URL: {TICKET_LINK}")
        print(f"Ticket status: {ticket.status.value}; assignee: {ticket.assignee}; reporter: {ticket.reporter}")
        print(f"Created {len(demo_rows)} notifications tied to the demo ticket:")
        for user_name, labels in sorted(by_user.items()):
            print(f"- {user_name}: {', '.join(labels)}")
        print("Open the bell and /notifications as Admin TeamWill or the assigned agent to verify unread sync.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
