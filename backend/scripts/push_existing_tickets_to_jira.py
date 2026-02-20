"""Backfill local tickets to Jira and link them for future outbound sync."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import or_

from app.db.session import SessionLocal
from app.models.ticket import Ticket
from app.services.tickets import ensure_jira_link_for_ticket


def main() -> None:
    db = SessionLocal()
    started = dt.datetime.now(dt.timezone.utc)
    try:
        candidates = (
            db.query(Ticket)
            .filter(or_(Ticket.jira_key.is_(None), Ticket.jira_key == ""))
            .order_by(Ticket.created_at.asc())
            .all()
        )
        total = len(candidates)
        linked = 0
        failed = 0

        print(f"[backfill] candidates={total}")
        for ticket in candidates:
            ok = ensure_jira_link_for_ticket(db, ticket)
            if ok:
                linked += 1
                print(f"[linked] {ticket.id} -> {ticket.jira_key}")
            else:
                failed += 1
                print(f"[failed] {ticket.id}")

        duration = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
        print(f"[done] linked={linked} failed={failed} duration_s={duration:.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

