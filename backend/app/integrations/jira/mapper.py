"""Mapping utilities from Jira issue payloads to internal normalized data."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from app.models.enums import TicketCategory, TicketPriority, TicketStatus

logger = logging.getLogger(__name__)

JIRA_SOURCE = "jsm"

STATUS_MAP = {
    "to do": TicketStatus.open,
    "open": TicketStatus.open,
    "new": TicketStatus.open,
    "in progress": TicketStatus.in_progress,
    "in-progress": TicketStatus.in_progress,
    "ongoing": TicketStatus.in_progress,
    "waiting for support": TicketStatus.pending,
    "pending": TicketStatus.pending,
    "waiting": TicketStatus.pending,
    "resolved": TicketStatus.resolved,
    "done": TicketStatus.closed,
    "closed": TicketStatus.closed,
}

PRIORITY_MAP = {
    "highest": TicketPriority.critical,
    "critical": TicketPriority.critical,
    "high": TicketPriority.high,
    "medium": TicketPriority.medium,
    "low": TicketPriority.low,
    "lowest": TicketPriority.low,
}

CATEGORY_MAP = {
    "incident": TicketCategory.service_request,
    "service request": TicketCategory.service_request,
    "task": TicketCategory.application,
    "bug": TicketCategory.application,
    "problem": TicketCategory.problem,
}


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Could not parse Jira datetime: %s", value)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(part for part in (_adf_to_text(item) for item in node) if part)
    if not isinstance(node, dict):
        return str(node)
    text = str(node.get("text") or "").strip()
    content = _adf_to_text(node.get("content"))
    return " ".join(piece for piece in [text, content] if piece).strip()


def _safe_title(issue_key: str, title: str | None) -> str:
    text = (title or "").strip()
    return text[:255] if text else f"Jira issue {issue_key}"


def map_status(fields: dict[str, Any]) -> TicketStatus:
    status_obj = fields.get("status") or {}
    status_name = str(status_obj.get("name") or "").strip().lower()
    if status_name in STATUS_MAP:
        return STATUS_MAP[status_name]
    category_key = str((status_obj.get("statusCategory") or {}).get("key") or "").strip().lower()
    if category_key == "done":
        return TicketStatus.resolved
    if category_key == "indeterminate":
        return TicketStatus.in_progress
    if category_key == "new":
        return TicketStatus.open
    logger.warning("Unknown Jira status '%s'; defaulting to open", status_name or category_key)
    return TicketStatus.open


def map_priority(fields: dict[str, Any]) -> TicketPriority:
    name = str((fields.get("priority") or {}).get("name") or "").strip().lower()
    if name in PRIORITY_MAP:
        return PRIORITY_MAP[name]
    if name:
        logger.warning("Unknown Jira priority '%s'; defaulting to medium", name)
    return TicketPriority.medium


def map_category(fields: dict[str, Any]) -> TicketCategory:
    issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip().lower()
    if issue_type in CATEGORY_MAP:
        return CATEGORY_MAP[issue_type]
    if issue_type:
        logger.warning("Unknown Jira issue type '%s'; defaulting to service_request", issue_type)
    return TicketCategory.service_request


@dataclass(frozen=True)
class NormalizedTicket:
    external_id: str
    external_source: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    assignee: str
    reporter: str
    tags: list[str]
    created_at: dt.datetime | None
    external_updated_at: dt.datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class NormalizedComment:
    external_comment_id: str
    external_source: str
    author: str
    content: str
    created_at: dt.datetime | None
    external_updated_at: dt.datetime | None
    raw_payload: dict[str, Any]


def map_issue(issue: dict[str, Any]) -> NormalizedTicket:
    fields = issue.get("fields") or {}
    issue_key = str(issue.get("key") or "").strip()
    if not issue_key:
        raise ValueError("missing_issue_key")

    summary = _safe_title(issue_key, fields.get("summary"))
    description = _adf_to_text(fields.get("description")) or summary
    assignee = str(((fields.get("assignee") or {}).get("displayName") or "Unassigned")).strip()
    reporter = str(((fields.get("reporter") or {}).get("displayName") or "Jira")).strip()
    tags = [str(label).strip() for label in (fields.get("labels") or []) if str(label).strip()]

    return NormalizedTicket(
        external_id=issue_key,
        external_source=JIRA_SOURCE,
        title=summary,
        description=description[:4000],
        status=map_status(fields),
        priority=map_priority(fields),
        category=map_category(fields),
        assignee=assignee[:255] or "Unassigned",
        reporter=reporter[:255] or "Jira",
        tags=tags[:20],
        created_at=_parse_datetime(str(fields.get("created") or "")),
        external_updated_at=_parse_datetime(str(fields.get("updated") or "")),
        raw_payload=issue,
    )


def map_issue_comment(comment: dict[str, Any]) -> NormalizedComment:
    comment_id = str(comment.get("id") or "").strip()
    if not comment_id:
        raise ValueError("missing_comment_id")
    author = str(((comment.get("author") or {}).get("displayName") or "Unknown")).strip()
    body = _adf_to_text(comment.get("body")) or "-"
    return NormalizedComment(
        external_comment_id=comment_id,
        external_source=JIRA_SOURCE,
        author=author[:255] or "Unknown",
        content=body[:8000],
        created_at=_parse_datetime(str(comment.get("created") or "")),
        external_updated_at=_parse_datetime(str(comment.get("updated") or "")),
        raw_payload=comment,
    )
