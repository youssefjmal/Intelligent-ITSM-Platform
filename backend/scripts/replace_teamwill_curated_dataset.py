"""Replace the current TEAMWILL sample dataset with a smaller curated set.

This script:
1. Backs up the current local TEAMWILL data and Jira project issues.
2. Deletes the old Jira TEAMWILL issues.
3. Purges the local sample dataset and related derived records.
4. Seeds a curated local dataset with exactly 2 problems.
5. Pushes the new tickets/comments to Jira, runs reconcile, syncs SLA, and refreshes Jira KB.
6. Prints a compact verification summary.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import or_

BASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BASE_DIR.parent
sys.path.append(str(BASE_DIR))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.integrations.jira.client import JiraClient  # noqa: E402
from app.integrations.jira.mapper import _parse_datetime as parse_jira_datetime  # noqa: E402
from app.integrations.jira.outbound import (  # noqa: E402
    _adf_from_text,
    _format_comment_text_for_jira,
    _sync_issue_status,
    create_jira_issue_for_ticket,
    sync_jira_issue_for_ticket,
)
from app.integrations.jira.schemas import JiraReconcileRequest  # noqa: E402
from app.integrations.jira.service import reconcile  # noqa: E402
from app.integrations.jira.sla_sync import sync_ticket_sla  # noqa: E402
from app.models.ai_sla_risk_evaluation import AiSlaRiskEvaluation  # noqa: E402
from app.models.automation_event import AutomationEvent  # noqa: E402
from app.models.enums import (  # noqa: E402
    ProblemStatus,
    SeniorityLevel,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    TicketType,
    UserRole,
)
from app.models.jira_sync_state import JiraSyncState  # noqa: E402
from app.models.kb_chunk import KBChunk  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.models.recommendation import Recommendation  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.jira_kb import state as jira_kb_state  # noqa: E402
from app.services.jira_kb.snapshot import _get_snapshot  # noqa: E402
from app.services.problems import recompute_problem_stats  # noqa: E402


def utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def backup_path() -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = REPO_ROOT / ".ops_backups"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"teamwill_dataset_backup_{stamp}.json"


def json_default(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def serialize_ticket(ticket: Ticket) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "ticket_type": ticket.ticket_type.value,
        "category": ticket.category.value,
        "assignee": ticket.assignee,
        "reporter": ticket.reporter,
        "problem_id": ticket.problem_id,
        "resolution": ticket.resolution,
        "due_at": ticket.due_at,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "first_action_at": ticket.first_action_at,
        "resolved_at": ticket.resolved_at,
        "jira_key": ticket.jira_key,
        "jira_issue_id": ticket.jira_issue_id,
        "tags": list(ticket.tags or []),
        "sla_status": ticket.sla_status,
        "sla_remaining_minutes": ticket.sla_remaining_minutes,
        "comments": [
            {
                "id": comment.id,
                "author": comment.author,
                "content": comment.content,
                "created_at": comment.created_at,
                "jira_comment_id": comment.jira_comment_id,
            }
            for comment in sorted(ticket.comments or [], key=lambda row: row.created_at)
        ],
    }


def serialize_problem(problem: Problem) -> dict[str, Any]:
    return {
        "id": problem.id,
        "title": problem.title,
        "category": problem.category.value,
        "status": problem.status.value,
        "created_at": problem.created_at,
        "updated_at": problem.updated_at,
        "last_seen_at": problem.last_seen_at,
        "resolved_at": problem.resolved_at,
        "occurrences_count": problem.occurrences_count,
        "active_count": problem.active_count,
        "root_cause": problem.root_cause,
        "workaround": problem.workaround,
        "permanent_fix": problem.permanent_fix,
        "similarity_key": problem.similarity_key,
    }


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "specializations": list(user.specializations or []),
        "seniority_level": user.seniority_level.value,
        "is_available": bool(user.is_available),
        "max_concurrent_tickets": int(user.max_concurrent_tickets or 0),
        "is_verified": bool(user.is_verified),
        "created_at": user.created_at,
    }


def fetch_project_issues(client: JiraClient, project_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_at = 0
    page_size = 50
    while True:
        page = client.search_jql(
            jql=f'project = "{project_key}" ORDER BY key ASC',
            start_at=start_at,
            max_results=page_size,
            fields="summary,description,status,priority,assignee,reporter,created,updated,duedate,labels,components,comment,customfield_10010",
        )
        issues = [item for item in list(page.get("issues") or []) if isinstance(item, dict)]
        if not issues:
            break
        for issue in issues:
            issue_key = str(issue.get("key") or "").strip()
            if not issue_key:
                continue
            full_issue = client.get_issue(
                issue_key,
                fields="summary,description,status,priority,assignee,reporter,created,updated,duedate,labels,components,comment,customfield_10010",
            )
            rows.append(full_issue)
        start_at += len(issues)
        if len(issues) < page_size:
            break
    return rows


def fetch_project_issue_summaries(client: JiraClient, project_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_at = 0
    page_size = 50
    while True:
        page = client.search_jql(
            jql=f'project = "{project_key}" ORDER BY key ASC',
            start_at=start_at,
            max_results=page_size,
            fields="summary,status,assignee,reporter,duedate,customfield_10010",
        )
        issues = [item for item in list(page.get("issues") or []) if isinstance(item, dict)]
        if not issues:
            break
        rows.extend(issues)
        start_at += len(issues)
        if len(issues) < page_size:
            break
    return rows


def write_backup() -> Path:
    path = backup_path()
    client = JiraClient()
    db = SessionLocal()
    try:
        payload = {
            "captured_at": dt.datetime.now(dt.timezone.utc),
            "project_key": settings.JIRA_PROJECT_KEY,
            "jira_base_url": settings.JIRA_BASE_URL,
            "users": [serialize_user(user) for user in db.query(User).order_by(User.name.asc()).all()],
            "problems": [serialize_problem(problem) for problem in db.query(Problem).order_by(Problem.id.asc()).all()],
            "tickets": [serialize_ticket(ticket) for ticket in db.query(Ticket).order_by(Ticket.id.asc()).all()],
            "recommendations": db.query(Recommendation).count(),
            "notifications": db.query(Notification).count(),
            "kb_chunks": db.query(KBChunk).count(),
            "jira_issues": fetch_project_issue_summaries(client, settings.JIRA_PROJECT_KEY.strip()),
        }
    finally:
        db.close()
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, default=json_default), encoding="utf-8")
    return path


PROBLEMS = [
    {
        "id": "PB-0201",
        "title": "Recurring VPN authentication and split-tunnel access incidents",
        "category": TicketCategory.network,
        "status": ProblemStatus.investigating,
        "created_at": utc("2026-03-07T08:00:00Z"),
        "updated_at": utc("2026-03-14T08:20:00Z"),
        "last_seen_at": utc("2026-03-14T08:20:00Z"),
        "resolved_at": None,
        "root_cause": "Firewall policy cleanup removed ERP split routes while a conditional access change shortened the MFA handshake window for VPN users.",
        "workaround": "Temporarily bypass the finance MFA condition for affected groups and force reconnects after refreshing the VPN policy bundle.",
        "permanent_fix": "Restore the approved split-tunnel route set, align the conditional access session lifetime with the VPN client, and add a post-change VPN smoke test.",
        "similarity_key": "network|vpn-mfa-split-tunnel-access|finance-remote-erp",
    },
    {
        "id": "PB-0202",
        "title": "Recurring SMTP relay trust-store and forwarding incidents",
        "category": TicketCategory.email,
        "status": ProblemStatus.known_error,
        "created_at": utc("2026-03-06T09:10:00Z"),
        "updated_at": utc("2026-03-14T09:35:00Z"),
        "last_seen_at": utc("2026-03-14T09:35:00Z"),
        "resolved_at": None,
        "root_cause": "Mail workers are not refreshing the relay trust store consistently after certificate renewals, and older forwarding connectors still reference retired identities.",
        "workaround": "Flush the deferred queue, redeploy the verified CA bundle, and reauthorize affected forwarding connectors before re-enabling traffic.",
        "permanent_fix": "Automate CA bundle rollout validation, pin the approved relay chain, and add a health check that blocks stale forwarding connector identities.",
        "similarity_key": "email|smtp-relay-trust-store-forwarding|cert-renewal-queue",
    },
]


TICKETS = [
    {
        "id": "TW-2001",
        "title": "VPN login blocked by MFA loop for finance team",
        "description": "Finance users can start the VPN login flow but they return to the MFA prompt repeatedly and never receive a connected session.",
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.network,
        "assignee": "Youssef Jmel",
        "reporter": "Maya Haddad",
        "problem_id": "PB-0201",
        "created_at": utc("2026-03-14T07:45:00Z"),
        "updated_at": utc("2026-03-14T09:15:00Z"),
        "due_at": utc("2026-03-15T12:00:00Z"),
        "resolution": None,
        "tags": ["vpn", "mfa", "finance", "access"],
        "comments": [
            ("c20011", "Karim Benali", "Azure sign-in logs show repeated MFA challenge restarts for the finance-vpn policy.", "2026-03-14T08:05:00Z"),
            ("c20012", "Youssef Jmel", "Temporary bypass applied for the finance-vpn group while we align the conditional access session lifetime.", "2026-03-14T09:10:00Z"),
        ],
    },
    {
        "id": "TW-2002",
        "title": "Remote sales VPN disconnects after 12 minutes",
        "description": "Remote sales users lose VPN connectivity after roughly 12 minutes even when traffic is active, causing CRM sessions to fail mid-call.",
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.network,
        "assignee": "Youssef Jmel",
        "reporter": "Sophie Leclerc",
        "problem_id": "PB-0201",
        "created_at": utc("2026-03-12T08:00:00Z"),
        "updated_at": utc("2026-03-12T13:20:00Z"),
        "due_at": utc("2026-03-13T12:00:00Z"),
        "resolution": "Raised the remote-sales VPN idle timeout from 900 seconds to 3600 seconds and cleared stale concentrator sessions.",
        "tags": ["vpn", "timeout", "remote-sales", "firewall"],
        "comments": [
            ("c20021", "Leila Ben Amor", "Concentrator logs confirm repeated idle-timeout events on the remote-sales VPN profile.", "2026-03-12T09:00:00Z"),
            ("c20022", "Youssef Jmel", "Raised the timeout to 3600 seconds, cleared stale sessions, and validated two hours of stable connectivity.", "2026-03-12T13:15:00Z"),
        ],
    },
    {
        "id": "TW-2003",
        "title": "Consultants cannot reach ERP over split tunnel VPN",
        "description": "External consultants connect to VPN successfully but traffic to the ERP subnet never routes through the tunnel after last weekend's firewall policy change.",
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.network,
        "assignee": "Youssef Jmel",
        "reporter": "Admin TeamWill",
        "problem_id": "PB-0201",
        "created_at": utc("2026-03-13T10:00:00Z"),
        "updated_at": utc("2026-03-13T12:10:00Z"),
        "due_at": utc("2026-03-18T12:00:00Z"),
        "resolution": None,
        "tags": ["vpn", "erp", "split-tunnel", "routing"],
        "comments": [
            ("c20031", "Leila Ben Amor", "The ERP subnet is missing from the split-tunnel route bundle deployed after the firewall cleanup.", "2026-03-13T10:40:00Z"),
            ("c20032", "Youssef Jmel", "Draft route fix prepared and queued for the next controlled firewall push window.", "2026-03-13T12:05:00Z"),
        ],
    },
    {
        "id": "TW-2004",
        "title": "Create VPN access for new logistics consultant",
        "description": "Provision standard VPN access for the new logistics consultant, including the approved warehouse dashboard and ERP read-only profile.",
        "status": TicketStatus.open,
        "priority": TicketPriority.medium,
        "ticket_type": TicketType.service_request,
        "category": TicketCategory.service_request,
        "assignee": "Youssef Jmel",
        "reporter": "Maya Haddad",
        "problem_id": None,
        "created_at": utc("2026-03-14T08:30:00Z"),
        "updated_at": utc("2026-03-14T09:40:00Z"),
        "due_at": utc("2026-03-19T12:00:00Z"),
        "resolution": None,
        "tags": ["vpn", "onboarding", "logistics"],
        "comments": [
            ("c20041", "Mohamed Chaari", "Identity proof and manager approval are complete; only the VPN group assignment remains.", "2026-03-14T08:55:00Z"),
            ("c20042", "Youssef Jmel", "Queued the consultant profile for the afternoon access batch and waiting for the final payroll reference.", "2026-03-14T09:35:00Z"),
        ],
    },
    {
        "id": "TW-2005",
        "title": "Password reset emails delayed by SMTP queue backlog",
        "description": "Password reset emails are delayed for more than 20 minutes because the SMTP relay queue is growing after yesterday's relay certificate renewal.",
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.email,
        "assignee": "Youssef Jmel",
        "reporter": "Maya Haddad",
        "problem_id": "PB-0202",
        "created_at": utc("2026-03-11T07:35:00Z"),
        "updated_at": utc("2026-03-11T12:45:00Z"),
        "due_at": utc("2026-03-12T12:00:00Z"),
        "resolution": "Installed the missing intermediate CA certificate on the active relay, restarted postfix, and drained the deferred queue.",
        "tags": ["smtp", "queue", "password-reset", "certificate"],
        "comments": [
            ("c20051", "Yassine Trabelsi", "Relay logs show TLS trust failures immediately after the certificate renewal on the primary mail node.", "2026-03-11T08:10:00Z"),
            ("c20052", "Youssef Jmel", "Intermediate CA installed, postfix restarted, and the queue drained back to normal within 15 minutes.", "2026-03-11T12:40:00Z"),
        ],
    },
    {
        "id": "TW-2006",
        "title": "Ticket notifications not sent after mail relay certificate renewal",
        "description": "Customer replies create tickets, but outbound ticket notifications are no longer delivered after the relay certificate renewal on March 13.",
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.email,
        "assignee": "Youssef Jmel",
        "reporter": "Sophie Leclerc",
        "problem_id": "PB-0202",
        "created_at": utc("2026-03-14T09:00:00Z"),
        "updated_at": utc("2026-03-14T10:20:00Z"),
        "due_at": utc("2026-03-16T12:00:00Z"),
        "resolution": None,
        "tags": ["smtp", "notifications", "relay", "certificate"],
        "comments": [
            ("c20061", "Yassine Trabelsi", "Two mail workers still have the old trust-store bundle and are refusing the renewed relay chain.", "2026-03-14T09:25:00Z"),
            ("c20062", "Youssef Jmel", "Temporary workaround is routing urgent notifications through the backup relay while the stale workers are redeployed.", "2026-03-14T10:15:00Z"),
        ],
    },
    {
        "id": "TW-2007",
        "title": "Procurement shared mailbox stopped forwarding to Teams",
        "description": "Messages sent to the procurement shared mailbox arrive normally, but the forwarding connector to the Teams channel stopped posting updates after connector rotation.",
        "status": TicketStatus.resolved,
        "priority": TicketPriority.medium,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.email,
        "assignee": "Youssef Jmel",
        "reporter": "Admin TeamWill",
        "problem_id": "PB-0202",
        "created_at": utc("2026-03-10T10:30:00Z"),
        "updated_at": utc("2026-03-10T14:20:00Z"),
        "due_at": utc("2026-03-11T12:00:00Z"),
        "resolution": "Rebuilt the forwarding rule with the new connector identity and reauthorized the Teams webhook used by the procurement mailbox.",
        "tags": ["mailbox", "forwarding", "teams", "connector"],
        "comments": [
            ("c20071", "Yassine Trabelsi", "Mailbox transport is healthy; the failure is isolated to the retired connector identity in the forwarding rule.", "2026-03-10T11:00:00Z"),
            ("c20072", "Youssef Jmel", "Forwarding rule rebuilt, webhook reauthorized, and test messages now post correctly to Teams.", "2026-03-10T14:15:00Z"),
        ],
    },
    {
        "id": "TW-2008",
        "title": "Create finance-alerts distribution list",
        "description": "Create a moderated finance-alerts distribution list for payroll, audit, and treasury notifications with the approved membership list.",
        "status": TicketStatus.resolved,
        "priority": TicketPriority.medium,
        "ticket_type": TicketType.service_request,
        "category": TicketCategory.email,
        "assignee": "Youssef Jmel",
        "reporter": "Maya Haddad",
        "problem_id": None,
        "created_at": utc("2026-03-09T09:00:00Z"),
        "updated_at": utc("2026-03-09T11:25:00Z"),
        "due_at": utc("2026-03-10T12:00:00Z"),
        "resolution": "Created finance-alerts@teamwill.com, added the approved members, and enabled moderation for external senders.",
        "tags": ["distribution-list", "finance", "email"],
        "comments": [
            ("c20081", "Mohamed Chaari", "Membership file and naming approval were attached by the finance manager.", "2026-03-09T09:20:00Z"),
            ("c20082", "Youssef Jmel", "Distribution list created and validated with an end-to-end notification test.", "2026-03-09T11:20:00Z"),
        ],
    },
    {
        "id": "TW-2009",
        "title": "Install Adobe Acrobat Pro for legal workstation",
        "description": "Install Adobe Acrobat Pro on the legal team's shared review workstation and confirm the device is licensed for PDF signature workflows.",
        "status": TicketStatus.open,
        "priority": TicketPriority.low,
        "ticket_type": TicketType.service_request,
        "category": TicketCategory.application,
        "assignee": "Youssef Jmel",
        "reporter": "Sophie Leclerc",
        "problem_id": None,
        "created_at": utc("2026-03-14T06:50:00Z"),
        "updated_at": utc("2026-03-14T08:15:00Z"),
        "due_at": utc("2026-03-20T12:00:00Z"),
        "resolution": None,
        "tags": ["software", "acrobat", "legal"],
        "comments": [
            ("c20091", "Amina Rafi", "One Acrobat Pro license is available in the legal pool and the installer package is ready.", "2026-03-14T07:20:00Z"),
            ("c20092", "Youssef Jmel", "Deployment has been queued for the next managed software window on the shared workstation.", "2026-03-14T08:10:00Z"),
        ],
    },
    {
        "id": "TW-2010",
        "title": "Grant admin access to staging VM for DevOps intern",
        "description": "Grant time-boxed admin access to the staging VM for the DevOps intern so they can complete deployment validation under audit logging.",
        "status": TicketStatus.resolved,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.service_request,
        "category": TicketCategory.security,
        "assignee": "Youssef Jmel",
        "reporter": "Admin TeamWill",
        "problem_id": None,
        "created_at": utc("2026-03-08T08:40:00Z"),
        "updated_at": utc("2026-03-08T12:10:00Z"),
        "due_at": utc("2026-03-09T12:00:00Z"),
        "resolution": "Granted time-boxed sudo access through the staging-admins group and enabled command audit logging for the temporary elevation window.",
        "tags": ["admin-access", "staging", "vm", "security"],
        "comments": [
            ("c20101", "Nadia Boucher", "Scope reviewed: staging only, 48-hour elevation, and audit logging required for every privileged command.", "2026-03-08T09:15:00Z"),
            ("c20102", "Youssef Jmel", "Temporary sudo access granted via the staging-admins group and audited successfully with a deployment validation test.", "2026-03-08T12:05:00Z"),
        ],
    },
    {
        "id": "TW-2011",
        "title": "API pods entering CrashLoopBackOff after node pool upgrade",
        "description": "Following the node pool upgrade from 1.27 to 1.29 on the production cluster, three API service pods are stuck in CrashLoopBackOff. Logs show OOMKilled events — the new node type has different memory allocation defaults. Other pods on the same deployment are running normally. The issue started immediately after the rolling upgrade completed.",
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Youssef Hamdi",
        "reporter": "DevOps Team",
        "problem_id": None,
        "created_at": utc("2026-03-20T09:00:00Z"),
        "updated_at": utc("2026-03-20T10:30:00Z"),
        "due_at": utc("2026-03-20T17:00:00Z"),
        "resolution": None,
        "tags": ["kubernetes", "k8s", "oom", "node-pool", "crashloopbackoff"],
        "comments": [
            ("c20111", "Leila Ben Amor", "kubectl describe pod confirms OOMKilled on all three replicas — memory request is 512Mi but new node type enforces a 256Mi limit by default.", "2026-03-20T09:45:00Z"),
            ("c20112", "Youssef Hamdi", "Patching the deployment manifest to set explicit resource limits; rolling restart in progress on staging first.", "2026-03-20T10:25:00Z"),
        ],
    },
    {
        "id": "TW-2012",
        "title": "New service deployment blocked by ImagePullBackOff on staging",
        "description": "The staging deployment of the new notification microservice is failing with ImagePullBackOff on all 3 replicas. The container image was pushed to the private registry 2 hours ago. The registry credentials secret in the staging namespace appears to have expired — it was last rotated 90 days ago and the token TTL is 90 days. Other services using the same registry are unaffected because they use cached image layers.",
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Leila Ben Amor",
        "reporter": "Finance Team",
        "problem_id": None,
        "created_at": utc("2026-03-21T11:00:00Z"),
        "updated_at": utc("2026-03-21T12:15:00Z"),
        "due_at": utc("2026-03-22T11:00:00Z"),
        "resolution": None,
        "tags": ["kubernetes", "imagepullbackoff", "registry", "secret", "staging"],
        "comments": [
            ("c20121", "Mohamed Chaari", "Confirmed: the registry pull secret in the staging namespace expired today. The token was created 90 days ago with a 90-day TTL.", "2026-03-21T11:35:00Z"),
            ("c20122", "Leila Ben Amor", "Rotating the registry service account token and patching the imagePullSecrets in the deployment manifest.", "2026-03-21T12:10:00Z"),
        ],
    },
    {
        "id": "TW-2013",
        "title": "Ollama inference latency spiked from 800ms to 12s after model swap",
        "description": "After switching from qwen3:4b to qwen3:7b on the recommendation service, LLM inference latency jumped from an average of 800ms to over 12 seconds per request. The host machine has 16GB RAM and no GPU — the larger model is being loaded in CPU-only mode. The embedding pipeline is unaffected. Agents are experiencing timeouts on the chatbot. The 4b model was working correctly before the change.",
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Youssef Hamdi",
        "reporter": "AI Team",
        "problem_id": None,
        "created_at": utc("2026-03-22T08:00:00Z"),
        "updated_at": utc("2026-03-22T09:20:00Z"),
        "due_at": utc("2026-03-22T16:00:00Z"),
        "resolution": None,
        "tags": ["ollama", "llm", "inference", "latency", "model", "cpu"],
        "comments": [
            ("c20131", "Nadia Boucher", "Profiling confirms the 7b model exceeds available RAM and is swapping to disk — effective throughput is 2 tokens/s versus 18 tokens/s on the 4b model.", "2026-03-22T08:50:00Z"),
            ("c20132", "Youssef Hamdi", "Rolling back to qwen3:4b while we evaluate a GPU node or a quantized 7b variant that fits within the memory envelope.", "2026-03-22T09:15:00Z"),
        ],
    },
    {
        "id": "TW-2014",
        "title": "KB semantic search returning unrelated tickets for VPN queries",
        "description": "The RAG retrieval pipeline is returning mail/email chunks as the top results when agents query about VPN connectivity issues. The cosine similarity scores for these cross-domain matches are above 0.72 which is above the retrieval threshold. Investigation shows the embedding model is conflating 'certificate' signals between VPN TLS certificates and mail relay SSL certificates. The context gate should be blocking these but the topic family overlap is causing false positives.",
        "status": TicketStatus.open,
        "priority": TicketPriority.medium,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Youssef Hamdi",
        "reporter": "AI Team",
        "problem_id": None,
        "created_at": utc("2026-03-22T13:00:00Z"),
        "updated_at": utc("2026-03-22T14:10:00Z"),
        "due_at": utc("2026-03-25T13:00:00Z"),
        "resolution": None,
        "tags": ["rag", "retrieval", "embedding", "vector", "context-gate"],
        "comments": [
            ("c20141", "Mohamed Chaari", "The auth_path and network_access topic families both contain 'certificate' — the context gate scores both topics equally and lets the mail chunk through.", "2026-03-22T13:40:00Z"),
            ("c20142", "Youssef Hamdi", "Investigating whether adding stricter anti-overlap tokens to the topic families or lowering the cross-domain similarity ceiling resolves the bleed.", "2026-03-22T14:05:00Z"),
        ],
    },
    {
        "id": "TW-2015",
        "title": "Notification service Kafka consumer lag exceeding 50k messages",
        "description": "The notification distribution consumer group is falling behind — current lag is 52,847 messages and growing. The consumer was processing 3,000 messages/minute before a deployment last Tuesday. After the deployment, throughput dropped to 400 messages/minute. The bottleneck appears to be in the database write path — each notification triggers 3 synchronous DB writes without batching. The message broker is healthy and producer throughput is unchanged.",
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Mohamed Chaari",
        "reporter": "Platform Team",
        "problem_id": None,
        "created_at": utc("2026-03-23T07:30:00Z"),
        "updated_at": utc("2026-03-23T09:00:00Z"),
        "due_at": utc("2026-03-23T14:00:00Z"),
        "resolution": None,
        "tags": ["kafka", "consumer-lag", "message-broker", "throughput", "notification"],
        "comments": [
            ("c20151", "Amina Rafi", "DB slow query log confirms each consumer handler is issuing 3 sequential INSERTs per message — batching was accidentally removed in the Tuesday deploy.", "2026-03-23T08:10:00Z"),
            ("c20152", "Mohamed Chaari", "Re-introducing batch writes (50 messages/flush) in a hotfix branch; estimating consumer will catch up within 2 hours once deployed.", "2026-03-23T08:55:00Z"),
        ],
    },
    {
        "id": "TW-2016",
        "title": "Circuit breaker open on payment gateway integration — all transactions failing",
        "description": "The circuit breaker on the payment gateway API client has been in OPEN state for 47 minutes. All payment transactions are failing fast without reaching the gateway. The circuit opened after the gateway returned 503 errors for 90 seconds during a maintenance window. The gateway is now healthy and returning 200s, but the circuit breaker has not reset because the half-open probe requests are timing out at the load balancer level — the LB health check timeout (2s) is shorter than the circuit breaker probe timeout (5s).",
        "status": TicketStatus.open,
        "priority": TicketPriority.critical,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.application,
        "assignee": "Nadia Boucher",
        "reporter": "Finance Team",
        "problem_id": None,
        "created_at": utc("2026-03-24T10:00:00Z"),
        "updated_at": utc("2026-03-24T10:55:00Z"),
        "due_at": utc("2026-03-24T12:00:00Z"),
        "resolution": None,
        "tags": ["circuit-breaker", "payment", "api-gateway", "load-balancer", "timeout"],
        "comments": [
            ("c20161", "Leila Ben Amor", "LB access logs confirm the half-open probes are being dropped at the 2s LB timeout before the circuit breaker can record a success.", "2026-03-24T10:30:00Z"),
            ("c20162", "Nadia Boucher", "Aligning LB health check timeout to 6s and manually forcing the circuit to HALF-OPEN to unblock transactions while the config change propagates.", "2026-03-24T10:50:00Z"),
        ],
    },
    {
        "id": "TW-2017",
        "title": "Deadlock detected on tickets table during concurrent SLA updates",
        "description": "The SLA monitor is producing deadlock errors when it attempts to update sla_status on multiple tickets simultaneously. The deadlock occurs because the SLA monitor acquires row locks in ticket_id ASC order while the Jira reconciliation process acquires them in updated_at DESC order. The two processes run concurrently every 5 minutes and occasionally overlap. Approximately 3% of SLA updates are failing silently due to deadlock rollbacks.",
        "status": TicketStatus.open,
        "priority": TicketPriority.high,
        "ticket_type": TicketType.incident,
        "category": TicketCategory.infrastructure,
        "assignee": "Youssef Hamdi",
        "reporter": "Platform Team",
        "problem_id": None,
        "created_at": utc("2026-03-25T08:00:00Z"),
        "updated_at": utc("2026-03-25T09:30:00Z"),
        "due_at": utc("2026-03-26T08:00:00Z"),
        "resolution": None,
        "tags": ["deadlock", "postgresql", "sla-monitor", "transaction", "lock"],
        "comments": [
            ("c20171", "Amina Rafi", "pg_locks confirms the cross-lock pattern: SLA monitor holds row A waiting for row B while reconcile holds row B waiting for row A — classic deadlock.", "2026-03-25T08:45:00Z"),
            ("c20172", "Youssef Hamdi", "Standardising both processes to acquire ticket row locks in ticket_id ASC order; will redeploy SLA monitor and reconcile together to eliminate the ordering conflict.", "2026-03-25T09:25:00Z"),
        ],
    },
]


def clear_jira_kb_cache() -> None:
    with jira_kb_state._snapshot_lock:
        jira_kb_state._snapshot_expires_at = None
        jira_kb_state._snapshot_rows = []
        jira_kb_state._kb_chunks_ready = None
        jira_kb_state._kb_chunks_checked_at = None
    with jira_kb_state._embedding_cache_lock:
        jira_kb_state._inmemory_embedding_cache = {}


def purge_jira_project(client: JiraClient, project_key: str) -> list[str]:
    issues = fetch_project_issue_summaries(client, project_key)
    deleted: list[str] = []
    for issue in reversed(issues):
        issue_key = str(issue.get("key") or "").strip()
        if not issue_key:
            continue
        client._request_empty("DELETE", f"/rest/api/3/issue/{issue_key}")  # noqa: SLF001
        deleted.append(issue_key)
    return deleted


def purge_local_dataset(project_key: str) -> None:
    db = SessionLocal()
    try:
        db.query(Notification).delete(synchronize_session=False)
        db.query(Recommendation).delete(synchronize_session=False)
        db.query(JiraSyncState).filter(JiraSyncState.project_key == project_key).delete(synchronize_session=False)
        db.query(KBChunk).filter(KBChunk.source_type.in_(["jira_issue", "jira_comment"])).delete(synchronize_session=False)
        db.query(AiSlaRiskEvaluation).delete(synchronize_session=False)
        db.query(AutomationEvent).delete(synchronize_session=False)
        db.query(TicketComment).delete(synchronize_session=False)
        db.query(Ticket).delete(synchronize_session=False)
        db.query(Problem).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def ensure_local_jira_user(db) -> None:  # noqa: ANN001
    jira_email = settings.JIRA_EMAIL.strip() or "youssefjmel42@gmail.com"
    user = (
        db.query(User)
        .filter(or_(User.email.ilike(jira_email), User.name.ilike("Youssef Jmel")))
        .first()
    )
    if user is None:
        user = User(
            email=jira_email,
            name="Youssef Jmel",
            role=UserRole.admin,
            specializations=["vpn", "identity", "mailbox_issues", "permissions"],
            seniority_level=SeniorityLevel.senior,
            is_available=True,
            max_concurrent_tickets=30,
            is_verified=True,
        )
        db.add(user)
    else:
        user.email = jira_email
        user.name = "Youssef Jmel"
        user.role = UserRole.admin
        user.specializations = ["vpn", "identity", "mailbox_issues", "permissions"]
        user.seniority_level = SeniorityLevel.senior
        user.is_available = True
        user.max_concurrent_tickets = 30
        user.is_verified = True
        db.add(user)
    db.flush()


def seed_local_dataset() -> None:
    db = SessionLocal()
    try:
        ensure_local_jira_user(db)
        for payload in PROBLEMS:
            problem = Problem(
                id=payload["id"],
                title=payload["title"],
                category=payload["category"],
                status=payload["status"],
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
                last_seen_at=payload["last_seen_at"],
                resolved_at=payload["resolved_at"],
                occurrences_count=0,
                active_count=0,
                root_cause=payload["root_cause"],
                workaround=payload["workaround"],
                permanent_fix=payload["permanent_fix"],
                similarity_key=payload["similarity_key"],
            )
            db.add(problem)

        for payload in TICKETS:
            comments = payload["comments"]
            comment_times = [utc(item[3]) for item in comments]
            ticket = Ticket(
                id=payload["id"],
                title=payload["title"],
                description=payload["description"],
                status=payload["status"],
                priority=payload["priority"],
                ticket_type=payload["ticket_type"],
                category=payload["category"],
                assignee=payload["assignee"],
                reporter=payload["reporter"],
                problem_id=payload["problem_id"],
                auto_assignment_applied=False,
                auto_priority_applied=False,
                assignment_model_version="seeded-manual",
                priority_model_version="seeded-manual",
                predicted_priority=payload["priority"],
                predicted_ticket_type=payload["ticket_type"],
                predicted_category=payload["category"],
                assignment_change_count=0,
                first_action_at=min(comment_times) if comment_times else None,
                resolved_at=max(comment_times) if payload["status"] == TicketStatus.resolved and comment_times else None,
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
                source="local",
                jira_key=None,
                jira_issue_id=None,
                jira_created_at=None,
                jira_updated_at=None,
                external_id=None,
                external_source=None,
                external_updated_at=None,
                last_synced_at=None,
                due_at=payload["due_at"],
                raw_payload=None,
                jira_sla_payload=None,
                sla_status=None,
                sla_first_response_due_at=None,
                sla_resolution_due_at=None,
                sla_first_response_breached=False,
                sla_resolution_breached=False,
                sla_first_response_completed_at=None,
                sla_resolution_completed_at=None,
                sla_remaining_minutes=None,
                sla_elapsed_minutes=None,
                sla_last_synced_at=None,
                priority_auto_escalated=False,
                priority_escalation_reason=None,
                priority_escalated_at=None,
                resolution=payload["resolution"],
                tags=list(payload["tags"]),
            )
            db.add(ticket)

            for comment_id, author, content, created_at in comments:
                db.add(
                    TicketComment(
                        id=comment_id,
                        ticket_id=payload["id"],
                        author=author,
                        content=content,
                        created_at=utc(created_at),
                        updated_at=None,
                        jira_comment_id=None,
                        jira_created_at=None,
                        jira_updated_at=None,
                        external_comment_id=None,
                        external_source=None,
                        external_updated_at=None,
                        raw_payload=None,
                    )
                )

        db.flush()
        for problem in db.query(Problem).all():
            recompute_problem_stats(db, problem.id)
        db.commit()
    finally:
        db.close()


def converge_issue_status(client: JiraClient, ticket: Ticket) -> None:
    if not ticket.jira_key or ticket.status == TicketStatus.open:
        return
    for _ in range(5):
        issue = client.get_issue(ticket.jira_key, fields="status")
        status_name = str(((issue.get("fields") or {}).get("status") or {}).get("name") or "").strip().lower()
        if ticket.status == TicketStatus.resolved and status_name in {"resolved", "done"}:
            return
        if ticket.status == TicketStatus.closed and status_name == "closed":
            return
        if not _sync_issue_status(client, ticket):
            return


def push_comments_for_ticket(client: JiraClient, ticket: Ticket, jira_actor_name: str) -> None:
    db = SessionLocal()
    try:
        db_ticket = db.get(Ticket, ticket.id)
        if db_ticket is None or not db_ticket.jira_key:
            raise RuntimeError(f"ticket_missing_after_create:{ticket.id}")

        comments = (
            db.query(TicketComment)
            .filter(TicketComment.ticket_id == db_ticket.id)
            .order_by(TicketComment.created_at.asc())
            .all()
        )
        for comment in comments:
            if comment.jira_comment_id:
                continue
            rendered = _format_comment_text_for_jira(
                comment.content,
                author_name=comment.author,
                jira_actor_name=jira_actor_name,
            )
            created = client._request(  # noqa: SLF001
                "POST",
                f"/rest/api/3/issue/{db_ticket.jira_key}/comment",
                json={"body": _adf_from_text(rendered)},
            )
            comment.jira_comment_id = str(created.get("id") or "").strip() or None
            comment.jira_created_at = parse_jira_datetime(str(created.get("created") or "")) or comment.jira_created_at
            comment.jira_updated_at = parse_jira_datetime(str(created.get("updated") or "")) or comment.jira_updated_at
            comment.external_comment_id = comment.jira_comment_id
            comment.external_source = "jira"
            comment.external_updated_at = comment.jira_updated_at
            comment.raw_payload = created
            db.add(comment)
        db.commit()
    finally:
        db.close()


def push_dataset_to_jira() -> dict[str, Any]:
    client = JiraClient()
    jira_actor_name = str((client.get_myself() or {}).get("displayName") or "").strip()
    summary: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        tickets = db.query(Ticket).order_by(Ticket.created_at.asc(), Ticket.id.asc()).all()
    finally:
        db.close()

    for seeded in tickets:
        db = SessionLocal()
        try:
            ticket = db.get(Ticket, seeded.id)
            if ticket is None:
                raise RuntimeError(f"missing_seed_ticket:{seeded.id}")
            jira_key = create_jira_issue_for_ticket(ticket)
            if not jira_key:
                raise RuntimeError(f"jira_create_failed:{ticket.id}")

            details = client.get_issue(jira_key, fields="created,updated,status,assignee,summary")
            now = dt.datetime.now(dt.timezone.utc)
            ticket.jira_key = jira_key
            ticket.jira_issue_id = str(details.get("id") or "").strip() or None
            ticket.jira_created_at = parse_jira_datetime(str(((details.get("fields") or {}).get("created") or ""))) or now
            ticket.jira_updated_at = parse_jira_datetime(str(((details.get("fields") or {}).get("updated") or ""))) or now
            ticket.external_id = jira_key
            ticket.external_source = "jira"
            ticket.external_updated_at = ticket.jira_updated_at
            ticket.last_synced_at = now
            db.add(ticket)
            db.commit()
            db.refresh(ticket)

            sync_jira_issue_for_ticket(ticket)
            converge_issue_status(client, ticket)
            refreshed = client.get_issue(jira_key, fields="updated")
            ticket.jira_updated_at = parse_jira_datetime(str(((refreshed.get("fields") or {}).get("updated") or ""))) or ticket.jira_updated_at
            ticket.external_updated_at = ticket.jira_updated_at
            ticket.last_synced_at = dt.datetime.now(dt.timezone.utc)
            db.add(ticket)
            db.commit()
        finally:
            db.close()

        push_comments_for_ticket(client, seeded, jira_actor_name)

        db = SessionLocal()
        try:
            ticket = db.get(Ticket, seeded.id)
            if ticket is None or not ticket.jira_key:
                raise RuntimeError(f"ticket_missing_for_sla:{seeded.id}")
            sync_ticket_sla(db, ticket, ticket.jira_key, jira_client=client)
            db.commit()
            issue = client.get_issue(
                ticket.jira_key,
                fields="summary,status,priority,assignee,reporter,duedate,components,customfield_10010,comment",
            )
            fields = issue.get("fields") or {}
            comments_total = int(((fields.get("comment") or {}).get("total") or 0))
            summary.append(
                {
                    "ticket_id": ticket.id,
                    "jira_key": ticket.jira_key,
                    "jira_status": str(((fields.get("status") or {}).get("name") or "")).strip(),
                    "jira_assignee": str(((fields.get("assignee") or {}).get("displayName") or "")).strip() or None,
                    "jira_due": str(fields.get("duedate") or "").strip() or None,
                    "jira_request_type": str((((fields.get("customfield_10010") or {}).get("requestType") or {}).get("name") or (fields.get("customfield_10010") or {}).get("name") or "")).strip() or None,
                    "jira_comments": comments_total,
                }
            )
        finally:
            db.close()

    return {"tickets": summary}


def run_reconcile_and_kb_refresh(project_key: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        result = reconcile(db, JiraReconcileRequest(project_key=project_key, lookback_days=30))
    finally:
        db.close()

    clear_jira_kb_cache()
    kb_rows = _get_snapshot()

    db = SessionLocal()
    try:
        jira_kb_count = (
            db.query(KBChunk)
            .filter(KBChunk.source_type.in_(["jira_issue", "jira_comment"]))
            .count()
        )
    finally:
        db.close()

    return {
        "reconcile": {
            "project_key": result.project_key,
            "issues_seen": result.issues_seen,
            "tickets_upserted": result.tickets_upserted,
            "comments_upserted": result.comments_upserted,
            "comments_updated": result.comments_updated,
            "errors": list(result.errors),
        },
        "kb_snapshot_rows": len(kb_rows),
        "jira_kb_chunks": jira_kb_count,
    }


def verify_dataset(project_key: str) -> dict[str, Any]:
    client = JiraClient()
    db = SessionLocal()
    try:
        local_tickets = db.query(Ticket).order_by(Ticket.id.asc()).all()
        local_tickets_by_id = {ticket.id: ticket for ticket in local_tickets}
        local_comments = db.query(TicketComment).count()
        local_problems = db.query(Problem).count()
        local_comment_ids = db.query(TicketComment).filter(TicketComment.jira_comment_id.isnot(None)).count()
        jira_issues = fetch_project_issues(client, project_key)
        jira_issue_count = len(jira_issues)

        jira_comment_total = 0
        assignee_mismatches: list[str] = []
        due_mismatches: list[str] = []
        request_type_breakdown: dict[str, int] = {}
        for issue in jira_issues:
            fields = issue.get("fields") or {}
            summary = str(fields.get("summary") or "").strip()
            local_id = ""
            if summary.startswith("[") and "]" in summary:
                local_id = summary.split("]", 1)[0].strip("[]")
            local_ticket = local_tickets_by_id.get(local_id)
            jira_comment_total += int(((fields.get("comment") or {}).get("total") or 0))
            request_type_name = str((((fields.get("customfield_10010") or {}).get("requestType") or {}).get("name") or (fields.get("customfield_10010") or {}).get("name") or "")).strip() or "unknown"
            request_type_breakdown[request_type_name] = request_type_breakdown.get(request_type_name, 0) + 1
            if local_ticket is None:
                continue
            jira_assignee = str(((fields.get("assignee") or {}).get("displayName") or "")).strip() or None
            if (local_ticket.assignee or None) != jira_assignee:
                assignee_mismatches.append(f"{local_ticket.id}:{jira_assignee}")
            jira_due = str(fields.get("duedate") or "").strip() or None
            local_due = local_ticket.due_at.date().isoformat() if local_ticket.due_at else None
            if jira_due != local_due:
                due_mismatches.append(f"{local_ticket.id}:{jira_due}")

        sla_tickets = (
            db.query(Ticket)
            .filter(Ticket.sla_status.isnot(None), Ticket.sla_status != "unknown")
            .count()
        )
        open_with_due = (
            db.query(Ticket)
            .filter(Ticket.status == TicketStatus.open, Ticket.due_at.isnot(None))
            .count()
        )
        resolved_with_resolution = (
            db.query(Ticket)
            .filter(Ticket.status == TicketStatus.resolved, Ticket.resolution.isnot(None))
            .count()
        )

        return {
            "local_tickets": len(local_tickets),
            "local_comments": local_comments,
            "local_comments_with_jira_ids": local_comment_ids,
            "local_problems": local_problems,
            "jira_issues": jira_issue_count,
            "jira_comments": jira_comment_total,
            "sla_tickets": sla_tickets,
            "open_with_due": open_with_due,
            "resolved_with_resolution": resolved_with_resolution,
            "assignee_mismatches": assignee_mismatches,
            "due_mismatches": due_mismatches,
            "request_type_breakdown": request_type_breakdown,
        }
    finally:
        db.close()


def main() -> int:
    project_key = settings.JIRA_PROJECT_KEY.strip()
    if not project_key:
        raise RuntimeError("missing_jira_project_key")

    print("Backing up current local/Jira TEAMWILL dataset...")
    backup = write_backup()
    print(f"Backup written: {backup}")

    client = JiraClient()
    print("Deleting existing Jira TEAMWILL issues...")
    deleted_keys = purge_jira_project(client, project_key)
    print(f"Deleted Jira issues: {len(deleted_keys)}")

    print("Purging local sample dataset...")
    purge_local_dataset(project_key)

    print("Seeding curated local dataset...")
    seed_local_dataset()

    print("Pushing curated tickets/comments to Jira...")
    push_summary = push_dataset_to_jira()

    print("Running reconcile and Jira KB refresh...")
    sync_summary = run_reconcile_and_kb_refresh(project_key)

    print("Verifying final DB/Jira state...")
    verification = verify_dataset(project_key)

    final_payload = {
        "backup_path": str(backup),
        "deleted_jira_issues": len(deleted_keys),
        "push_summary": push_summary,
        "sync_summary": sync_summary,
        "verification": verification,
    }
    print(json.dumps(final_payload, ensure_ascii=True, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
