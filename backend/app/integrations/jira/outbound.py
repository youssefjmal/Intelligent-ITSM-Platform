"""Outbound helpers to push locally created tickets to Jira."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from app.core.config import settings
from app.integrations.jira.client import JiraClient
from app.models.enums import TicketPriority, TicketStatus
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

PRIORITY_TO_JIRA: dict[TicketPriority, str] = {
    TicketPriority.critical: "Highest",
    TicketPriority.high: "High",
    TicketPriority.medium: "Medium",
    TicketPriority.low: "Low",
}

PREFERRED_ISSUE_TYPES = ("Incident", "Service Request", "Task", "Bug", "Story")
STATUS_TO_JIRA_NAMES: dict[TicketStatus, tuple[str, ...]] = {
    TicketStatus.open: ("open", "to do", "new"),
    TicketStatus.in_progress: ("in progress", "in-progress", "ongoing"),
    TicketStatus.waiting_for_customer: ("waiting for customer",),
    TicketStatus.waiting_for_support_vendor: ("waiting for support", "waiting for vendor", "waiting for support/vendor"),
    TicketStatus.pending: ("waiting for support", "waiting for vendor", "pending", "waiting"),
    TicketStatus.resolved: ("resolved", "done"),
    TicketStatus.closed: ("closed",),
}


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
    text = (ticket.description or "").strip()
    return text or "No details provided."


def _identity(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _candidate_queries(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    candidates = [raw]
    if "@" in raw:
        candidates.append(raw.split("@", 1)[0])
    parts = [part for part in re.split(r"[\s._-]+", raw) if part]
    if len(parts) >= 2:
        candidates.append(" ".join(parts[:2]))
    candidates.extend(parts[:3])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = candidate.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _resolve_user_account_id(client: JiraClient, user_value: str | None) -> str | None:
    raw = (user_value or "").strip()
    if not raw:
        return None

    raw_identity = _identity(raw)
    best_fallback: str | None = None

    for query in _candidate_queries(raw):
        try:
            users = client.search_users(query, max_results=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira user search failed for query '%s': %s", query, exc)
            continue
        if not users:
            continue

        for user in users:
            account_id = str(user.get("accountId") or user.get("id") or "").strip()
            if not account_id:
                continue
            if not bool(user.get("active", True)):
                continue

            display_name = str(user.get("displayName") or "").strip()
            email = str(user.get("emailAddress") or "").strip()
            if raw_identity and raw_identity in {
                _identity(display_name),
                _identity(email),
                _identity(account_id),
            }:
                return account_id
            if best_fallback is None:
                best_fallback = account_id
    return best_fallback


def _jira_user_field(account_id: str | None) -> dict[str, str] | None:
    value = (account_id or "").strip()
    if not value:
        return None
    return {"accountId": value}


def _normalized_status(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _sync_issue_status(client: JiraClient, ticket: Ticket) -> bool:
    target_names = STATUS_TO_JIRA_NAMES.get(ticket.status)
    if not target_names or not ticket.jira_key:
        return False

    current_status = ""
    try:
        issue = client.get_issue(ticket.jira_key, fields="status")
        current_status = _normalized_status(str(((issue.get("fields") or {}).get("status") or {}).get("name") or ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira status fetch failed for %s: %s", ticket.jira_key, exc)

    normalized_targets = {_normalized_status(name) for name in target_names}
    if current_status and current_status in normalized_targets:
        return False

    try:
        transitions = client.get_issue_transitions(ticket.jira_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira transitions fetch failed for %s: %s", ticket.jira_key, exc)
        return False

    for transition in transitions:
        transition_id = str(transition.get("id") or "").strip()
        to_name = _normalized_status(str(((transition.get("to") or {}).get("name") or "")))
        if not transition_id:
            continue
        if to_name in normalized_targets:
            try:
                return client.transition_issue(ticket.jira_key, transition_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Jira transition failed for %s via %s: %s", ticket.jira_key, transition_id, exc)
                return False
    return False


def _issue_fields(client: JiraClient, ticket: Ticket, *, project_key: str, issue_type_id: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": issue_type_id},
        "summary": f"[{ticket.id}] {ticket.title}"[:255],
        "description": _adf_from_text(_description(ticket)),
        "labels": _labels(ticket),
        "priority": {"name": _resolve_priority_name(ticket.priority)},
    }
    assignee_field = _jira_user_field(_resolve_user_account_id(client, ticket.assignee))
    if assignee_field:
        fields["assignee"] = assignee_field
    reporter_field = _jira_user_field(_resolve_user_account_id(client, ticket.reporter))
    if reporter_field:
        fields["reporter"] = reporter_field
    return fields


def _retry_create_issue(client: JiraClient, ticket: Ticket, fields: dict[str, Any]) -> dict[str, Any] | None:
    attempts: list[dict[str, Any]] = [
        fields,
        {key: value for key, value in fields.items() if key not in {"reporter"}},
        {key: value for key, value in fields.items() if key not in {"reporter", "assignee"}},
        {key: value for key, value in fields.items() if key not in {"reporter", "assignee", "priority"}},
    ]
    last_exc: Exception | None = None
    for index, payload in enumerate(attempts, start=1):
        try:
            return client._request("POST", "/rest/api/3/issue", json={"fields": payload})  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Jira create issue attempt %s failed for %s: %s", index, ticket.id, exc)
    if last_exc:
        logger.warning("Jira push failed for %s after retries: %s", ticket.id, last_exc)
    return None


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

    fields = _issue_fields(client, ticket, project_key=project_key, issue_type_id=issue_type_id)
    created = _retry_create_issue(client, ticket, fields)
    if not isinstance(created, dict):
        return None

    issue_key = str(created.get("key") or "").strip()
    if not issue_key:
        logger.warning("Jira push failed for %s: missing issue key in response", ticket.id)
        return None
    return issue_key


def sync_jira_issue_for_ticket(ticket: Ticket) -> bool:
    """Push local ticket changes to Jira for an existing linked issue."""
    if not _jira_ready():
        return False
    issue_key = str(ticket.jira_key or ticket.external_id or "").strip()
    if not issue_key:
        return False

    client = JiraClient()
    client.timeout = 8.0
    client.max_retries = 1

    project_key = _project_key_from_issue_key(issue_key) or _detect_project_key(client)
    if not project_key:
        logger.warning("Jira update skipped for %s: missing project key", ticket.id)
        return False
    issue_type_id = _resolve_issue_type_id(client, project_key)
    if not issue_type_id:
        logger.warning("Jira update skipped for %s: cannot resolve issue type", ticket.id)
        return False

    fields = _issue_fields(client, ticket, project_key=project_key, issue_type_id=issue_type_id)
    update_payload = {key: value for key, value in fields.items() if key not in {"project", "issuetype"}}

    attempts: list[dict[str, Any]] = [
        update_payload,
        {key: value for key, value in update_payload.items() if key not in {"reporter"}},
        {key: value for key, value in update_payload.items() if key not in {"reporter", "assignee"}},
    ]
    updated = False
    for index, payload in enumerate(attempts, start=1):
        try:
            client.update_issue_fields(issue_key, payload)
            updated = True
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira issue update attempt %s failed for %s: %s", index, ticket.id, exc)

    status_changed = _sync_issue_status(client, ticket)
    return updated or status_changed


def add_jira_comment_for_ticket(ticket: Ticket, comment_text: str) -> bool:
    """Push a local ticket comment to Jira for an existing linked issue."""
    if not _jira_ready():
        return False
    issue_key = str(ticket.jira_key or ticket.external_id or "").strip()
    if not issue_key:
        return False
    normalized = (comment_text or "").strip()
    if not normalized:
        return False

    client = JiraClient()
    client.timeout = 8.0
    client.max_retries = 1
    try:
        return client.add_issue_comment(issue_key, _adf_from_text(normalized))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira comment push failed for %s: %s", ticket.id, exc)
        return False
