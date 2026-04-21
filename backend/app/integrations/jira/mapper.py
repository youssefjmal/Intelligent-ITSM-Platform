"""Mapping utilities from Jira issue payloads to normalized ticket/comment data."""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.ticket_limits import MAX_TAG_LEN, MAX_TAGS
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.integrations.jira.summary import normalize_local_ticket_title
from app.services.ai.taxonomy import CATEGORY_HINTS as AI_CATEGORY_HINTS

logger = logging.getLogger(__name__)

JIRA_SOURCE = "jira"

STATUS_MAP = {
    "to do": TicketStatus.open,
    "open": TicketStatus.open,
    "new": TicketStatus.open,
    "in progress": TicketStatus.in_progress,
    "in-progress": TicketStatus.in_progress,
    "ongoing": TicketStatus.in_progress,
    "waiting for customer": TicketStatus.waiting_for_customer,
    "waiting for support": TicketStatus.open,
    "waiting for vendor": TicketStatus.waiting_for_support_vendor,
    "waiting for support/vendor": TicketStatus.waiting_for_support_vendor,
    "pending": TicketStatus.pending,
    "waiting": TicketStatus.pending,
    "resolved": TicketStatus.resolved,
    "done": TicketStatus.resolved,
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
    "service request": TicketCategory.service_request,
    "email request": TicketCategory.email,
    "task": TicketCategory.application,
    "bug": TicketCategory.application,
    "problem": TicketCategory.problem,
}
CATEGORY_COMPONENT_MAP = {
    "application": TicketCategory.application,
    "email": TicketCategory.email,
    "hardware": TicketCategory.hardware,
    "infrastructure": TicketCategory.infrastructure,
    "network": TicketCategory.network,
    "problem": TicketCategory.problem,
    "security": TicketCategory.security,
    "service request": TicketCategory.service_request,
}

TICKET_TYPE_MAP = {
    "incident": TicketType.incident,
    "report an incident": TicketType.incident,
    "report a system problem": TicketType.incident,
    "report broken hardware": TicketType.incident,
    "service request": TicketType.service_request,
    "email request": TicketType.service_request,
    "emailed request": TicketType.service_request,
    "get it help": TicketType.service_request,
    "task": TicketType.incident,
    "bug": TicketType.incident,
    "problem": TicketType.incident,
}

REQUEST_TYPE_ISSUE_TYPE_MAP = {
    "10001": TicketType.incident,
    "10002": TicketType.service_request,
}
CATEGORY_LABEL_PREFIX = "category_"
COMMENT_AUTHOR_PREFIX_RE = re.compile(r"^(?:\[platform author:\s*(?P<bracket>[^\]]+)\]|original platform author:\s*(?P<plain>[^\n]+))\s*", re.IGNORECASE)
LOCAL_ASSIGNEE_LABEL_PREFIX = "local_assignee_"
LOCAL_REPORTER_LABEL_PREFIX = "local_reporter_"
_CATEGORY_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)


def _request_type_payload(fields: dict[str, Any]) -> dict[str, Any]:
    payload = fields.get("customfield_10010") or {}
    if isinstance(payload, dict):
        request_type = payload.get("requestType")
        if isinstance(request_type, dict):
            return request_type
        return payload
    return {}


def _label_values(fields: dict[str, Any]) -> list[str]:
    return [str(label).strip().lower() for label in list(fields.get("labels") or []) if str(label).strip()]


def _category_from_labels(fields: dict[str, Any]) -> TicketCategory | None:
    for label in _label_values(fields):
        if not label.startswith(CATEGORY_LABEL_PREFIX):
            continue
        raw = label[len(CATEGORY_LABEL_PREFIX):].strip().replace("-", "_")
        try:
            return TicketCategory(raw)
        except ValueError:
            continue
    return None


def _category_from_components(fields: dict[str, Any]) -> TicketCategory | None:
    for component in list(fields.get("components") or []):
        if not isinstance(component, dict):
            continue
        name = str(component.get("name") or "").strip().lower()
        if name in CATEGORY_COMPONENT_MAP:
            return CATEGORY_COMPONENT_MAP[name]
    return None


def _category_text_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _CATEGORY_TOKEN_RE.findall(text or "")]


def _token_sequence_present(tokens: list[str], phrase_tokens: tuple[str, ...]) -> bool:
    if not phrase_tokens:
        return False
    if len(phrase_tokens) == 1:
        return phrase_tokens[0] in set(tokens)
    max_start = len(tokens) - len(phrase_tokens) + 1
    if max_start <= 0:
        return False
    for start in range(max_start):
        if tuple(tokens[start : start + len(phrase_tokens)]) == phrase_tokens:
            return True
    return False


def _category_from_text(fields: dict[str, Any]) -> TicketCategory | None:
    summary = str(fields.get("summary") or "").strip()
    description = _normalize_text(fields.get("description"))
    request_type_payload = _request_type_payload(fields)
    request_type_name = str(
        request_type_payload.get("name")
        or request_type_payload.get("defaultName")
        or ""
    ).strip()
    label_text = " ".join(_label_values(fields))
    component_text = " ".join(
        str(component.get("name") or "").strip()
        for component in list(fields.get("components") or [])
        if isinstance(component, dict)
    )
    text = " ".join(
        part
        for part in [summary, description, request_type_name, label_text, component_text]
        if str(part).strip()
    )
    tokens = _category_text_tokens(text)
    title_tokens = _category_text_tokens(summary)
    if not tokens:
        return None

    scores: dict[TicketCategory, float] = {}
    for category_name, hints in AI_CATEGORY_HINTS.items():
        try:
            category = TicketCategory(category_name)
        except ValueError:
            continue
        score = 0.0
        for phrase in hints:
            phrase_tokens = tuple(_category_text_tokens(str(phrase)))
            if not phrase_tokens:
                continue
            if _token_sequence_present(tokens, phrase_tokens):
                weight = 1.0 + (0.2 * max(0, len(phrase_tokens) - 1))
                score += weight
                if _token_sequence_present(title_tokens, phrase_tokens):
                    score += 0.35
        if score > 0.0:
            scores[category] = round(score, 4)

    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0].value), reverse=True)
    top_category, top_score = ranked[0]
    second_score = float(ranked[1][1]) if len(ranked) > 1 else 0.0

    if top_category != TicketCategory.service_request:
        if top_score >= max(1.0, second_score + 0.35):
            return top_category
        return None

    best_domain = next(
        (
            (category, float(score))
            for category, score in ranked
            if category != TicketCategory.service_request
        ),
        None,
    )
    if best_domain is None:
        return None
    domain_category, domain_score = best_domain
    if domain_score >= 1.0 and domain_score + 0.1 >= top_score:
        return domain_category
    return None


def _titleize_slug(value: str) -> str:
    words = [part for part in str(value or "").strip().replace("-", "_").split("_") if part]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _local_assignee_from_labels(fields: dict[str, Any]) -> str | None:
    for label in _label_values(fields):
        if not label.startswith(LOCAL_ASSIGNEE_LABEL_PREFIX):
            continue
        slug = label[len(LOCAL_ASSIGNEE_LABEL_PREFIX):].strip()
        titleized = _titleize_slug(slug)
        if titleized:
            return titleized
    return None


def _local_reporter_from_labels(fields: dict[str, Any]) -> str | None:
    for label in _label_values(fields):
        if not label.startswith(LOCAL_REPORTER_LABEL_PREFIX):
            continue
        slug = label[len(LOCAL_REPORTER_LABEL_PREFIX):].strip()
        titleized = _titleize_slug(slug)
        if titleized:
            return titleized
    return None

def _normalize_tags(values: list[str]) -> list[str]:
    """Normalize Jira labels/components to local tag limits."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = str(raw or "").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN:
            tag = tag[:MAX_TAG_LEN].strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(tag)
        if len(normalized) >= MAX_TAGS:
            break
    return normalized


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) == 10 and normalized.count("-") == 2:
        normalized = f"{normalized}T12:00:00+00:00"
    candidates = [
        normalized.replace("Z", "+00:00"),
        normalized,
    ]
    for candidate in candidates:
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    formats = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")
    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(normalized, fmt)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    logger.warning("Could not parse Jira datetime: %s", value)
    return None


def _text_from_adf(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(part for part in (_text_from_adf(item) for item in node) if part)
    if not isinstance(node, dict):
        return str(node)

    parts: list[str] = []
    text = node.get("text")
    if isinstance(text, str):
        parts.append(text)
    content = node.get("content")
    if isinstance(content, list):
        for child in content:
            child_text = _text_from_adf(child)
            if child_text:
                parts.append(child_text)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _normalize_text(raw_body: Any) -> str:
    if isinstance(raw_body, str):
        text = raw_body
    else:
        text = _text_from_adf(raw_body)
    return " ".join(text.split()).strip()


def _safe_title(issue_key: str, title: str | None) -> str:
    text = normalize_local_ticket_title(title)
    return text[:255] if text else f"Jira issue {issue_key}"


def _safe_description(description: str, *, summary: str, issue_key: str) -> str:
    text = " ".join(str(description or "").split()).strip()
    if len(text) >= 5:
        return text[:4000]

    summary_text = " ".join(str(summary or "").split()).strip()
    if len(summary_text) >= 5:
        return summary_text[:4000]

    fallback = f"Jira issue {issue_key}"
    return fallback[:4000]


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
    category_from_label = _category_from_labels(fields)
    if category_from_label is not None:
        return category_from_label

    category_from_component = _category_from_components(fields)
    if category_from_component is not None:
        return category_from_component

    request_type_payload = _request_type_payload(fields)
    request_type_name = str(
        request_type_payload.get("name")
        or request_type_payload.get("defaultName")
        or ""
    ).strip().lower()
    if request_type_name == "report broken hardware":
        return TicketCategory.hardware
    if request_type_name == "report a system problem":
        return TicketCategory.application
    if request_type_name == "request admin access":
        return TicketCategory.security
    if request_type_name == "request new hardware":
        return TicketCategory.hardware
    if request_type_name == "request new software":
        return TicketCategory.application
    if request_type_name == "request a new account":
        return TicketCategory.service_request
    if request_type_name == "emailed request":
        return TicketCategory.email

    category_from_text = _category_from_text(fields)
    if category_from_text is not None:
        return category_from_text

    issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip().lower()
    if issue_type in {"incident", "report an incident"}:
        return TicketCategory.application
    if issue_type in CATEGORY_MAP:
        return CATEGORY_MAP[issue_type]
    if issue_type:
        logger.warning("Unknown Jira issue type '%s'; defaulting to application", issue_type)
    return TicketCategory.application


def map_ticket_type(fields: dict[str, Any]) -> TicketType:
    request_type_payload = _request_type_payload(fields)
    if request_type_payload:
        request_type_issue_type_id = str(request_type_payload.get("issueTypeId") or "").strip()
        mapped_issue_type = REQUEST_TYPE_ISSUE_TYPE_MAP.get(request_type_issue_type_id)
        if mapped_issue_type is not None:
            return mapped_issue_type

        request_type_name = str(
            request_type_payload.get("name")
            or request_type_payload.get("defaultName")
            or ""
        ).strip().lower()
        if request_type_name in TICKET_TYPE_MAP:
            return TICKET_TYPE_MAP[request_type_name]

    issue_type = str((fields.get("issuetype") or {}).get("name") or "").strip().lower()
    if issue_type in TICKET_TYPE_MAP:
        return TICKET_TYPE_MAP[issue_type]
    if issue_type:
        logger.warning("Unknown Jira issue type '%s'; defaulting ticket type to incident", issue_type)
    return TicketType.incident


@dataclass(frozen=True)
class NormalizedTicket:
    jira_key: str
    jira_issue_id: str
    source: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    ticket_type: TicketType
    category: TicketCategory
    assignee: str
    reporter: str
    tags: list[str]
    jira_created_at: dt.datetime | None
    jira_updated_at: dt.datetime | None
    due_at: dt.datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class NormalizedComment:
    jira_comment_id: str
    author: str
    content: str
    jira_created_at: dt.datetime | None
    jira_updated_at: dt.datetime | None
    raw_payload: dict[str, Any]


def map_issue(issue: dict[str, Any]) -> NormalizedTicket:
    fields = issue.get("fields") or {}
    issue_key = str(issue.get("key") or "").strip()
    issue_id = str(issue.get("id") or "").strip()
    if not issue_key:
        raise ValueError("missing_issue_key")

    summary = _safe_title(issue_key, fields.get("summary"))
    description = _safe_description(_normalize_text(fields.get("description")), summary=summary, issue_key=issue_key)
    assignee = _local_assignee_from_labels(fields) or str(((fields.get("assignee") or {}).get("displayName") or "")).strip()
    assignee = assignee or "Unassigned"
    reporter = _local_reporter_from_labels(fields) or str(((fields.get("reporter") or {}).get("displayName") or "")).strip()
    reporter = reporter or "Jira"
    tags = [str(label).strip() for label in (fields.get("labels") or []) if str(label).strip()]
    component_names = [
        str(component.get("name") or "").strip()
        for component in list(fields.get("components") or [])
        if isinstance(component, dict) and str(component.get("name") or "").strip()
    ]
    tags.extend(component_names)
    tags = _normalize_tags(tags)

    return NormalizedTicket(
        jira_key=issue_key,
        jira_issue_id=issue_id or issue_key,
        source=JIRA_SOURCE,
        title=summary,
        description=description,
        status=map_status(fields),
        priority=map_priority(fields),
        ticket_type=map_ticket_type(fields),
        category=map_category(fields),
        assignee=assignee[:255] or "Unassigned",
        reporter=reporter[:255] or "Jira",
        tags=tags,
        jira_created_at=_parse_datetime(str(fields.get("created") or "")),
        jira_updated_at=_parse_datetime(str(fields.get("updated") or "")),
        due_at=_parse_datetime(str(fields.get("duedate") or "")),
        raw_payload=issue,
    )


def map_issue_comment(comment: dict[str, Any]) -> NormalizedComment:
    comment_id = str(comment.get("id") or "").strip()
    if not comment_id:
        raise ValueError("missing_comment_id")
    author = str(((comment.get("author") or {}).get("displayName") or "Unknown")).strip()
    body = _normalize_text(comment.get("body")) or "-"
    match = COMMENT_AUTHOR_PREFIX_RE.match(body)
    if match:
        preserved_author = str(match.group("bracket") or match.group("plain") or "").strip()
        if preserved_author:
            author = preserved_author
        body = body[match.end():].strip() or "-"
    return NormalizedComment(
        jira_comment_id=comment_id,
        author=author[:255] or "Unknown",
        content=body[:8000],
        jira_created_at=_parse_datetime(str(comment.get("created") or "")),
        jira_updated_at=_parse_datetime(str(comment.get("updated") or "")),
        raw_payload=comment,
    )
