"""Outbound helpers to push locally created tickets to Jira."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core.config import settings
from app.integrations.jira.client import JiraClient
from app.models.enums import TicketPriority
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

PRIORITY_TO_JIRA: dict[TicketPriority, str] = {
    TicketPriority.critical: "Highest",
    TicketPriority.high: "High",
    TicketPriority.medium: "Medium",
    TicketPriority.low: "Low",
}

PREFERRED_ISSUE_TYPES = ("Incident", "Service Request", "Task", "Bug", "Story")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _jira_ready() -> bool:
    return bool(
        settings.JIRA_BASE_URL.strip()
        and settings.JIRA_EMAIL.strip()
        and settings.JIRA_API_TOKEN.strip()
    )


def _adf_from_text(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        lines = ["No details provided."]
    blocks = []
    for line in lines[:40]:
        blocks.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line[:1000]}],
            }
        )
    return {"type": "doc", "version": 1, "content": blocks}


def _project_key_from_issue_key(issue_key: str) -> str | None:
    value = (issue_key or "").strip()
    if "-" not in value:
        return None
    head = value.split("-", 1)[0].strip()
    return head or None


def _detect_project_key(client: JiraClient) -> str | None:
    configured = (settings.JIRA_PROJECT_KEY or "").strip()
    if configured:
        return configured
    since_iso = (_utcnow() - dt.timedelta(days=3650)).strftime("%Y-%m-%d %H:%M")
    try:
        data = client.search_updated_issues(
            since_iso=since_iso,
            start_at=0,
            max_results=1,
            project_key=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira project detection failed: %s", exc)
        return None
    issues = list(data.get("issues") or [])
    if not issues:
        return None
    issue_key = str((issues[0] or {}).get("key") or "")
    return _project_key_from_issue_key(issue_key)


def _resolve_issue_type_id(client: JiraClient, project_key: str) -> str | None:
    try:
        payload = client._request("GET", f"/rest/api/3/project/{project_key}")  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira issue type resolution failed: %s", exc)
        return None
    issue_types = [item for item in list(payload.get("issueTypes") or []) if isinstance(item, dict)]
    if not issue_types:
        return None

    by_name = {str(item.get("name") or "").strip().casefold(): item for item in issue_types}
    for name in PREFERRED_ISSUE_TYPES:
        matched = by_name.get(name.casefold())
        if matched and str(matched.get("id") or "").strip():
            return str(matched.get("id")).strip()

    fallback = issue_types[0]
    issue_type_id = str(fallback.get("id") or "").strip()
    return issue_type_id or None


def _resolve_priority_name(priority: TicketPriority) -> str:
    return PRIORITY_TO_JIRA.get(priority, "Medium")


def _labels(ticket: Ticket) -> list[str]:
    labels = [
        "local-itsm",
        f"local_{ticket.id.lower().replace('-', '_')}",
        f"priority_{ticket.priority.value}",
        f"category_{ticket.category.value}",
    ]
    for tag in ticket.tags or []:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(tag).strip().lower())
        cleaned = cleaned.strip("_")
        if cleaned:
            labels.append(cleaned[:32])

    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if not label or label in seen:
            continue
        seen.add(label)
        deduped.append(label)
        if len(deduped) >= 12:
            break
    return deduped


def _description(ticket: Ticket) -> str:
    chunks = [
        "Created from local ITSM platform",
        f"Local ticket ID: {ticket.id}",
        f"Reporter: {ticket.reporter}",
        f"Assignee: {ticket.assignee}",
        "",
        (ticket.description or "").strip(),
    ]
    return "\n".join(chunks).strip()


def create_jira_issue_for_ticket(ticket: Ticket) -> str | None:
    """Push a local ticket to Jira and return Jira issue key."""
    if not _jira_ready():
        return None

    client = JiraClient()
    # Keep outbound sync non-blocking for the UI path.
    client.timeout = 8.0
    client.max_retries = 1
    project_key = _detect_project_key(client)
    if not project_key:
        logger.warning("Jira push skipped for %s: missing project key", ticket.id)
        return None

    issue_type_id = _resolve_issue_type_id(client, project_key)
    if not issue_type_id:
        logger.warning("Jira push skipped for %s: no issue type available in project %s", ticket.id, project_key)
        return None

    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": issue_type_id},
        "summary": f"[{ticket.id}] {ticket.title}"[:255],
        "description": _adf_from_text(_description(ticket)),
        "labels": _labels(ticket),
        "priority": {"name": _resolve_priority_name(ticket.priority)},
    }

    try:
        created = client._request("POST", "/rest/api/3/issue", json={"fields": fields})  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        # Retry once without optional fields to avoid schema mismatch issues.
        logger.warning("Jira push failed for %s (with optional fields): %s", ticket.id, exc)
        minimal_fields = dict(fields)
        minimal_fields.pop("priority", None)
        try:
            created = client._request("POST", "/rest/api/3/issue", json={"fields": minimal_fields})  # noqa: SLF001
        except Exception as retry_exc:  # noqa: BLE001
            logger.warning("Jira push failed for %s (minimal payload): %s", ticket.id, retry_exc)
            return None

    issue_key = str(created.get("key") or "").strip()
    if not issue_key:
        logger.warning("Jira push failed for %s: missing issue key in response", ticket.id)
        return None
    return issue_key
