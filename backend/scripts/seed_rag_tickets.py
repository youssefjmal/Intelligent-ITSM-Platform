"""Seed RAG-focused tickets and comments for local verification."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import TicketCategory, TicketPriority, TicketStatus  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402


def parse_dt(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


RAG_TICKETS = [
    {
        "id": "TW-3101",
        "jira_key": "ITSM-3101",
        "jira_issue_id": "3101",
        "title": "VPN sessions drop every 15 minutes for remote sales",
        "description": (
            "Remote sales users are disconnected from VPN around every 15 minutes. "
            "Issue started after firewall policy update during maintenance."
        ),
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "category": TicketCategory.network,
        "assignee": "Leila Ben Amor",
        "reporter": "Sales Ops",
        "created_at": "2026-02-15T08:10:00Z",
        "updated_at": "2026-02-15T13:40:00Z",
        "resolution": "Raised firewall idle timeout from 900s to 3600s and cleared stale sessions.",
        "tags": ["vpn", "timeout", "remote", "firewall"],
        "comments": [
            {
                "id": "rc3101-1",
                "jira_comment_id": "3101-1",
                "author": "Leila Ben Amor",
                "content": (
                    "Checked concentrator logs: frequent tunnel renegotiation and idle-timeout events "
                    "for remote-sales policy."
                ),
                "created_at": "2026-02-15T09:05:00Z",
            },
            {
                "id": "rc3101-2",
                "jira_comment_id": "3101-2",
                "author": "Network Bot",
                "content": "Firewall profile remote-sales has idle timeout set to 900 seconds.",
                "created_at": "2026-02-15T09:22:00Z",
            },
            {
                "id": "rc3101-3",
                "jira_comment_id": "3101-3",
                "author": "Leila Ben Amor",
                "content": (
                    "Applied timeout=3600, flushed stale sessions, and asked users to reconnect. "
                    "No disconnects observed in the next two hours."
                ),
                "created_at": "2026-02-15T13:35:00Z",
            },
        ],
    },
    {
        "id": "TW-3102",
        "jira_key": "ITSM-3102",
        "jira_issue_id": "3102",
        "title": "MFA loop during VPN login for finance team",
        "description": (
            "Finance users are stuck in a repeated MFA prompt and cannot complete VPN authentication. "
            "Symptoms appeared after identity provider policy change."
        ),
        "status": TicketStatus.in_progress,
        "priority": TicketPriority.critical,
        "category": TicketCategory.security,
        "assignee": "Nadia Boucher",
        "reporter": "Finance Manager",
        "created_at": "2026-02-16T07:40:00Z",
        "updated_at": "2026-02-16T11:25:00Z",
        "resolution": None,
        "tags": ["vpn", "mfa", "identity", "security"],
        "comments": [
            {
                "id": "rc3102-1",
                "jira_comment_id": "3102-1",
                "author": "Nadia Boucher",
                "content": (
                    "Correlated failures with new conditional access rule. Token lifetime is too short "
                    "for legacy VPN client handshake."
                ),
                "created_at": "2026-02-16T08:30:00Z",
            },
            {
                "id": "rc3102-2",
                "jira_comment_id": "3102-2",
                "author": "Nadia Boucher",
                "content": (
                    "Temporary workaround: bypass rule for finance-vpn group and enforce device compliance check."
                ),
                "created_at": "2026-02-16T10:55:00Z",
            },
        ],
    },
    {
        "id": "TW-3103",
        "jira_key": "ITSM-3103",
        "jira_issue_id": "3103",
        "title": "Outgoing emails stuck in outbox after SMTP certificate rotation",
        "description": (
            "Support notifications are queued but not delivered. SMTP server rejects TLS handshake after "
            "certificate rotation."
        ),
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "category": TicketCategory.email,
        "assignee": "Yassine Trabelsi",
        "reporter": "Service Desk",
        "created_at": "2026-02-16T09:15:00Z",
        "updated_at": "2026-02-16T15:00:00Z",
        "resolution": (
            "Installed missing intermediate CA certificate, restarted postfix, and validated SPF/DKIM "
            "for outbound domain."
        ),
        "tags": ["smtp", "tls", "certificate", "email"],
        "comments": [
            {
                "id": "rc3103-1",
                "jira_comment_id": "3103-1",
                "author": "Yassine Trabelsi",
                "content": "TLS error seen in logs: unable to verify first certificate from relay.",
                "created_at": "2026-02-16T10:02:00Z",
            },
            {
                "id": "rc3103-2",
                "jira_comment_id": "3103-2",
                "author": "Youssef Hamdi",
                "content": "Added intermediate CA bundle and restarted postfix service.",
                "created_at": "2026-02-16T12:10:00Z",
            },
            {
                "id": "rc3103-3",
                "jira_comment_id": "3103-3",
                "author": "Yassine Trabelsi",
                "content": "Queue drained and notifications are delivered. Monitoring for 24h.",
                "created_at": "2026-02-16T14:55:00Z",
            },
        ],
    },
    {
        "id": "TW-3104",
        "jira_key": "ITSM-3104",
        "jira_issue_id": "3104",
        "title": "CSV export contains garbled UTF-8 characters in large reports",
        "description": (
            "Managers report broken accents and symbols when exporting CSV files above 20k rows. "
            "Issue likely related to inconsistent encoding and delimiter handling."
        ),
        "status": TicketStatus.pending,
        "priority": TicketPriority.medium,
        "category": TicketCategory.application,
        "assignee": "Amina Rafi",
        "reporter": "Reporting Team",
        "created_at": "2026-02-17T08:20:00Z",
        "updated_at": "2026-02-17T10:30:00Z",
        "resolution": None,
        "tags": ["csv", "encoding", "export", "reporting"],
        "comments": [
            {
                "id": "rc3104-1",
                "jira_comment_id": "3104-1",
                "author": "Amina Rafi",
                "content": (
                    "Root cause suspected in exporter using locale-dependent default encoding instead of UTF-8."
                ),
                "created_at": "2026-02-17T09:10:00Z",
            },
            {
                "id": "rc3104-2",
                "jira_comment_id": "3104-2",
                "author": "Amina Rafi",
                "content": (
                    "Prepared fix: force UTF-8 BOM for Excel compatibility and sanitize separators in text fields."
                ),
                "created_at": "2026-02-17T10:25:00Z",
            },
        ],
    },
]


def seed_rag_tickets() -> None:
    db = SessionLocal()
    inserted_tickets = 0
    inserted_comments = 0

    try:
        for payload in RAG_TICKETS:
            ticket = db.query(Ticket).filter(Ticket.id == payload["id"]).first()
            if ticket is None:
                ticket = Ticket(
                    id=payload["id"],
                    title=payload["title"],
                    description=payload["description"],
                    status=payload["status"],
                    priority=payload["priority"],
                    category=payload["category"],
                    assignee=payload["assignee"],
                    reporter=payload["reporter"],
                    source="jira",
                    jira_key=payload["jira_key"],
                    jira_issue_id=payload["jira_issue_id"],
                    external_source="jira",
                    external_id=payload["jira_key"],
                    created_at=parse_dt(payload["created_at"]),
                    updated_at=parse_dt(payload["updated_at"]),
                    resolution=payload["resolution"],
                    tags=payload["tags"],
                )
                db.add(ticket)
                inserted_tickets += 1

            existing_comment_ids = {
                row[0]
                for row in db.query(TicketComment.id)
                .filter(TicketComment.ticket_id == payload["id"])
                .all()
            }
            for comment_payload in payload["comments"]:
                comment_id = comment_payload["id"]
                if comment_id in existing_comment_ids:
                    continue

                ticket.comments.append(
                    TicketComment(
                        id=comment_id,
                        author=comment_payload["author"],
                        content=comment_payload["content"],
                        jira_comment_id=comment_payload["jira_comment_id"],
                        created_at=parse_dt(comment_payload["created_at"]),
                    )
                )
                inserted_comments += 1

        db.commit()
        total_tickets = db.query(Ticket).count()
        total_comments = db.query(TicketComment).count()
        print(f"inserted_tickets={inserted_tickets}")
        print(f"inserted_comments={inserted_comments}")
        print(f"tickets_total={total_tickets}")
        print(f"comments_total={total_comments}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_rag_tickets()
