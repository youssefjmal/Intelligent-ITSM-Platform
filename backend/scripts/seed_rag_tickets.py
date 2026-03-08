"""Seed RAG-focused tickets, comments, and linked problems for local verification."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import ProblemStatus, TicketCategory, TicketPriority, TicketStatus  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402


def parse_dt(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


RAG_PROBLEMS = [
    {
        "id": "PB-0091",
        "title": "Recurring SMTP TLS and queue backlog incidents",
        "category": TicketCategory.email,
        "status": ProblemStatus.investigating,
        "occurrences_count": 5,
        "active_count": 2,
        "root_cause": (
            "Certificate chain drift and inconsistent SMTP relay policy after monthly security updates."
        ),
        "workaround": (
            "Apply verified relay profile, flush deferred queue, and temporarily route critical notifications "
            "through backup relay."
        ),
        "permanent_fix": (
            "Automate certificate chain validation, pin trusted relays, and run post-change SMTP smoke tests."
        ),
        "similarity_key": "email|smtp-tls-queue-backlog|smtp-cert-rotation",
        "created_at": "2026-02-15T08:00:00Z",
        "updated_at": "2026-02-24T18:10:00Z",
        "last_seen_at": "2026-02-24T17:55:00Z",
        "resolved_at": None,
    },
]


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
        "problem_id": "PB-0091",
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
    {
        "id": "TW-3201",
        "jira_key": "ITSM-3201",
        "jira_issue_id": "3201",
        "problem_id": "PB-0091",
        "title": "SMTP TLS handshake fails after relay certificate rotation",
        "description": (
            "Password reset and alert emails fail intermittently after relay certificate rotation. "
            "Handshake fails on nodes running old trust bundle."
        ),
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "category": TicketCategory.email,
        "assignee": "Yassine Trabelsi",
        "reporter": "Identity Team",
        "created_at": "2026-02-18T07:30:00Z",
        "updated_at": "2026-02-18T13:05:00Z",
        "resolution": (
            "Synced CA bundle across mail nodes, pinned relay certificate chain, and added startup check "
            "that blocks SMTP service when trust store is outdated."
        ),
        "tags": ["smtp", "tls", "cert-rotation", "password-reset"],
        "comments": [
            {
                "id": "rc3201-1",
                "jira_comment_id": "3201-1",
                "author": "Yassine Trabelsi",
                "content": "Failure reproduced on two nodes with stale cert bundle timestamp.",
                "created_at": "2026-02-18T08:05:00Z",
            },
            {
                "id": "rc3201-2",
                "jira_comment_id": "3201-2",
                "author": "Platform Bot",
                "content": "Queue length peaked at 14,200 deferred messages during handshake errors.",
                "created_at": "2026-02-18T09:15:00Z",
            },
            {
                "id": "rc3201-3",
                "jira_comment_id": "3201-3",
                "author": "Youssef Hamdi",
                "content": "Rolled out trust-store sync + relay pinning to all mail workers.",
                "created_at": "2026-02-18T12:25:00Z",
            },
        ],
    },
    {
        "id": "TW-3202",
        "jira_key": "ITSM-3202",
        "jira_issue_id": "3202",
        "problem_id": "PB-0091",
        "title": "Mail queue backlog delays verification emails for new users",
        "description": (
            "New user verification emails are delayed by 20-40 minutes during queue spikes. "
            "Backpressure appears after incident bursts and retry storms."
        ),
        "status": TicketStatus.in_progress,
        "priority": TicketPriority.critical,
        "category": TicketCategory.email,
        "assignee": "Youssef Hamdi",
        "reporter": "Customer Success",
        "created_at": "2026-02-19T10:20:00Z",
        "updated_at": "2026-02-20T14:40:00Z",
        "resolution": None,
        "tags": ["email-queue", "verification", "latency", "smtp"],
        "comments": [
            {
                "id": "rc3202-1",
                "jira_comment_id": "3202-1",
                "author": "Youssef Hamdi",
                "content": "Observed repeated retries to same relay endpoint with 421 tempfail.",
                "created_at": "2026-02-19T10:55:00Z",
            },
            {
                "id": "rc3202-2",
                "jira_comment_id": "3202-2",
                "author": "Yassine Trabelsi",
                "content": (
                    "Enabled queue partitioning for verification traffic and raised worker concurrency from 8 to 20."
                ),
                "created_at": "2026-02-20T09:05:00Z",
            },
            {
                "id": "rc3202-3",
                "jira_comment_id": "3202-3",
                "author": "NOC Team",
                "content": "P95 delivery dropped from 31m to 8m, still above SLA target of 5m.",
                "created_at": "2026-02-20T14:20:00Z",
            },
        ],
    },
    {
        "id": "TW-3203",
        "jira_key": "ITSM-3203",
        "jira_issue_id": "3203",
        "problem_id": "PB-0091",
        "title": "NDR 4.4.1 spikes for Microsoft domains after postfix update",
        "description": (
            "After postfix patch rollout, outbound emails to Microsoft domains show high 4.4.1 delays "
            "and deferred retries."
        ),
        "status": TicketStatus.closed,
        "priority": TicketPriority.high,
        "category": TicketCategory.email,
        "assignee": "Yassine Trabelsi",
        "reporter": "Service Desk",
        "created_at": "2026-02-21T08:05:00Z",
        "updated_at": "2026-02-21T16:45:00Z",
        "resolution": (
            "Rolled back strict TLS ciphers for external relay profile, introduced per-domain route rules, "
            "and validated delivery success with 1k synthetic messages."
        ),
        "tags": ["smtp", "ndr", "postfix", "delivery"],
        "comments": [
            {
                "id": "rc3203-1",
                "jira_comment_id": "3203-1",
                "author": "Yassine Trabelsi",
                "content": "Issue isolated to microsoft domains; gmail and yahoo unaffected.",
                "created_at": "2026-02-21T09:10:00Z",
            },
            {
                "id": "rc3203-2",
                "jira_comment_id": "3203-2",
                "author": "Email Bot",
                "content": "TLS negotiation failure count exceeded threshold: 426 in 30 minutes.",
                "created_at": "2026-02-21T10:40:00Z",
            },
            {
                "id": "rc3203-3",
                "jira_comment_id": "3203-3",
                "author": "Youssef Hamdi",
                "content": "Route override deployed and queue normalized in 18 minutes.",
                "created_at": "2026-02-21T16:15:00Z",
            },
        ],
    },
    {
        "id": "TW-3204",
        "jira_key": "ITSM-3204",
        "jira_issue_id": "3204",
        "problem_id": "PB-0091",
        "title": "Incident alert notifications delayed during priority-1 spikes",
        "description": (
            "During P1 incident bursts, alert notifications to on-call engineers are delayed by up to 12 minutes "
            "because mail queue workers are saturated."
        ),
        "status": TicketStatus.pending,
        "priority": TicketPriority.high,
        "category": TicketCategory.email,
        "assignee": "Youssef Hamdi",
        "reporter": "Incident Commander",
        "created_at": "2026-02-24T09:20:00Z",
        "updated_at": "2026-02-24T17:55:00Z",
        "resolution": None,
        "tags": ["alerts", "oncall", "queue", "priority-routing"],
        "comments": [
            {
                "id": "rc3204-1",
                "jira_comment_id": "3204-1",
                "author": "Incident Commander",
                "content": "Observed delayed on-call alerts in two P1 exercises this week.",
                "created_at": "2026-02-24T10:10:00Z",
            },
            {
                "id": "rc3204-2",
                "jira_comment_id": "3204-2",
                "author": "Youssef Hamdi",
                "content": (
                    "Plan: reserve dedicated high-priority queue lane for incident notifications."
                ),
                "created_at": "2026-02-24T12:45:00Z",
            },
        ],
    },
    {
        "id": "TW-3205",
        "jira_key": "ITSM-3205",
        "jira_issue_id": "3205",
        "title": "Intermittent 502 responses from ticket API after warm restart",
        "description": (
            "API gateway returns intermittent 502 for /tickets/search after warm restarts. "
            "Failure correlates with exhausted DB pool under burst traffic."
        ),
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "category": TicketCategory.infrastructure,
        "assignee": "Youssef Hamdi",
        "reporter": "API Monitoring",
        "created_at": "2026-02-22T07:40:00Z",
        "updated_at": "2026-02-22T13:30:00Z",
        "resolution": (
            "Increased SQLAlchemy pool size, enabled pre-ping, and staggered worker warm-up with health gate "
            "to avoid connection storms."
        ),
        "tags": ["api", "502", "db-pool", "restart"],
        "comments": [
            {
                "id": "rc3205-1",
                "jira_comment_id": "3205-1",
                "author": "Youssef Hamdi",
                "content": "During warm restart all workers request connections simultaneously.",
                "created_at": "2026-02-22T08:15:00Z",
            },
            {
                "id": "rc3205-2",
                "jira_comment_id": "3205-2",
                "author": "SRE Bot",
                "content": "Peak failed requests: 4.8% for 7 minutes; mostly /tickets/search.",
                "created_at": "2026-02-22T09:00:00Z",
            },
            {
                "id": "rc3205-3",
                "jira_comment_id": "3205-3",
                "author": "Youssef Hamdi",
                "content": "After fix rollout error rate remained below 0.1% under load test.",
                "created_at": "2026-02-22T13:20:00Z",
            },
        ],
    },
    {
        "id": "TW-3206",
        "jira_key": "ITSM-3206",
        "jira_issue_id": "3206",
        "title": "Dashboard stale metrics due to missed cache invalidation",
        "description": (
            "Ticket dashboard KPIs remain stale for up to 30 minutes after ticket updates. "
            "Invalidation event is not published when status changes from pending to in-progress."
        ),
        "status": TicketStatus.in_progress,
        "priority": TicketPriority.medium,
        "category": TicketCategory.application,
        "assignee": "Amina Rafi",
        "reporter": "Ops Lead",
        "created_at": "2026-02-23T09:45:00Z",
        "updated_at": "2026-02-24T11:20:00Z",
        "resolution": None,
        "tags": ["dashboard", "cache", "kpi", "event-bus"],
        "comments": [
            {
                "id": "rc3206-1",
                "jira_comment_id": "3206-1",
                "author": "Amina Rafi",
                "content": "Found missing publish call in status transition branch pending->in-progress.",
                "created_at": "2026-02-23T10:20:00Z",
            },
            {
                "id": "rc3206-2",
                "jira_comment_id": "3206-2",
                "author": "Karim Benali",
                "content": "Added integration test asserting cache invalidation on every status transition.",
                "created_at": "2026-02-24T11:10:00Z",
            },
        ],
    },
    {
        "id": "TW-3207",
        "jira_key": "ITSM-3207",
        "jira_issue_id": "3207",
        "title": "VPN reconnect storm after ISP failover",
        "description": (
            "After ISP failover, all branch VPN clients attempted immediate reconnect causing tunnel flaps "
            "and packet loss for 15 minutes."
        ),
        "status": TicketStatus.resolved,
        "priority": TicketPriority.medium,
        "category": TicketCategory.network,
        "assignee": "Leila Ben Amor",
        "reporter": "NOC Team",
        "created_at": "2026-02-20T06:40:00Z",
        "updated_at": "2026-02-20T09:55:00Z",
        "resolution": (
            "Added jittered reconnect backoff profile and enabled secondary tunnel pre-establishment "
            "to smooth failover events."
        ),
        "tags": ["vpn", "failover", "backoff", "network"],
        "comments": [
            {
                "id": "rc3207-1",
                "jira_comment_id": "3207-1",
                "author": "Leila Ben Amor",
                "content": "Failover generated 2,900 reconnect attempts in first 90 seconds.",
                "created_at": "2026-02-20T07:10:00Z",
            },
            {
                "id": "rc3207-2",
                "jira_comment_id": "3207-2",
                "author": "Network Bot",
                "content": "Packet loss dropped from 18% to <1% after reconnect jitter policy.",
                "created_at": "2026-02-20T09:30:00Z",
            },
        ],
    },
    {
        "id": "TW-3208",
        "jira_key": "ITSM-3208",
        "jira_issue_id": "3208",
        "title": "Knowledge search misses SMTP incidents with certificate wording",
        "description": (
            "Knowledge search fails to return prior SMTP incidents when users query with cert-chain terms "
            "instead of TLS handshake keywords."
        ),
        "status": TicketStatus.open,
        "priority": TicketPriority.medium,
        "category": TicketCategory.application,
        "assignee": "Amina Rafi",
        "reporter": "Support Training",
        "created_at": "2026-02-24T08:30:00Z",
        "updated_at": "2026-02-24T16:05:00Z",
        "resolution": None,
        "tags": ["rag", "search", "smtp", "knowledge-base"],
        "comments": [
            {
                "id": "rc3208-1",
                "jira_comment_id": "3208-1",
                "author": "Support Training",
                "content": (
                    "Queries like 'certificate chain trust' return no SMTP hits despite similar past incidents."
                ),
                "created_at": "2026-02-24T09:05:00Z",
            },
            {
                "id": "rc3208-2",
                "jira_comment_id": "3208-2",
                "author": "Amina Rafi",
                "content": "Will add synonym expansion for cert-chain, relay trust, and TLS handshake.",
                "created_at": "2026-02-24T15:55:00Z",
            },
        ],
    },
]


def _upsert_problem(db, payload: dict) -> bool:
    row = db.query(Problem).filter(Problem.id == payload["id"]).first()
    created = row is None
    if row is None:
        row = Problem(id=payload["id"])
        db.add(row)

    row.title = payload["title"]
    row.category = payload["category"]
    row.status = payload["status"]
    row.occurrences_count = payload["occurrences_count"]
    row.active_count = payload["active_count"]
    row.root_cause = payload["root_cause"]
    row.workaround = payload["workaround"]
    row.permanent_fix = payload["permanent_fix"]
    row.similarity_key = payload["similarity_key"]
    row.created_at = parse_dt(payload["created_at"])
    row.updated_at = parse_dt(payload["updated_at"])
    row.last_seen_at = parse_dt(payload["last_seen_at"])
    row.resolved_at = parse_dt(payload["resolved_at"]) if payload["resolved_at"] else None
    return created


def _upsert_ticket(db, payload: dict) -> tuple[Ticket, bool]:
    row = db.query(Ticket).filter(Ticket.id == payload["id"]).first()
    created = row is None
    if row is None:
        row = Ticket(id=payload["id"])
        db.add(row)

    row.title = payload["title"]
    row.description = payload["description"]
    row.status = payload["status"]
    row.priority = payload["priority"]
    row.category = payload["category"]
    row.assignee = payload["assignee"]
    row.reporter = payload["reporter"]
    row.problem_id = payload.get("problem_id")
    row.source = "jira"
    row.jira_key = payload["jira_key"]
    row.jira_issue_id = payload["jira_issue_id"]
    row.external_source = "jira"
    row.external_id = payload["jira_key"]
    row.created_at = parse_dt(payload["created_at"])
    row.updated_at = parse_dt(payload["updated_at"])
    row.resolution = payload["resolution"]
    row.tags = payload["tags"]
    return row, created


def seed_rag_tickets() -> None:
    db = SessionLocal()
    inserted_problems = 0
    updated_problems = 0
    inserted_tickets = 0
    updated_tickets = 0
    inserted_comments = 0
    updated_comments = 0

    try:
        for problem_payload in RAG_PROBLEMS:
            created = _upsert_problem(db, problem_payload)
            if created:
                inserted_problems += 1
            else:
                updated_problems += 1

        for payload in RAG_TICKETS:
            ticket, created = _upsert_ticket(db, payload)
            if created:
                inserted_tickets += 1
            else:
                updated_tickets += 1

            existing_comments = {
                row.id: row
                for row in db.query(TicketComment)
                .filter(TicketComment.ticket_id == payload["id"])
                .all()
            }

            for comment_payload in payload["comments"]:
                comment_id = comment_payload["id"]
                comment_row = existing_comments.get(comment_id)
                if comment_row is None:
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
                    continue

                comment_row.author = comment_payload["author"]
                comment_row.content = comment_payload["content"]
                comment_row.jira_comment_id = comment_payload["jira_comment_id"]
                comment_row.created_at = parse_dt(comment_payload["created_at"])
                updated_comments += 1

        db.commit()

        total_tickets = db.query(Ticket).count()
        total_comments = db.query(TicketComment).count()
        total_problems = db.query(Problem).count()
        linked_to_problem = (
            db.query(Ticket)
            .filter(Ticket.problem_id.in_([payload["id"] for payload in RAG_PROBLEMS]))
            .count()
        )

        print(f"inserted_problems={inserted_problems}")
        print(f"updated_problems={updated_problems}")
        print(f"inserted_tickets={inserted_tickets}")
        print(f"updated_tickets={updated_tickets}")
        print(f"inserted_comments={inserted_comments}")
        print(f"updated_comments={updated_comments}")
        print(f"problems_total={total_problems}")
        print(f"tickets_total={total_tickets}")
        print(f"comments_total={total_comments}")
        print(f"tickets_linked_to_seeded_problem={linked_to_problem}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_rag_tickets()
