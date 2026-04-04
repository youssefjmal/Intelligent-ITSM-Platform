"""Outbound helpers to push locally created tickets to Jira."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.jira.client import JiraClient
from app.integrations.jira.roles import sync_jira_project_roles_for_identity
from app.integrations.jira.summary import normalize_local_ticket_title
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.models.ticket import Ticket
from app.models.user import User

logger = logging.getLogger(__name__)
CATEGORY_LABEL_PREFIX = "category_"
COMMENT_AUTHOR_PREFIX = "Original platform author:"
LOCAL_ASSIGNEE_LABEL_PREFIX = "local_assignee_"
LOCAL_REPORTER_LABEL_PREFIX = "local_reporter_"

PRIORITY_TO_JIRA: dict[TicketPriority, str] = {
    TicketPriority.critical: "Highest",
    TicketPriority.high: "High",
    TicketPriority.medium: "Medium",
    TicketPriority.low: "Low",
}

PREFERRED_ISSUE_TYPES_BY_TICKET_TYPE: dict[TicketType, tuple[str, ...]] = {
    TicketType.incident: (
        "[System] Incident",
        "Incident",
        "Task",
        "Bug",
        "Story",
    ),
    TicketType.service_request: (
        "[System] Service request",
        "[System] Service request with approvals",
        "Service Request",
        "Task",
        "Story",
    ),
}
STATUS_TO_JIRA_NAMES: dict[TicketStatus, tuple[str, ...]] = {
    TicketStatus.open: ("waiting for support", "open", "to do", "new"),
    TicketStatus.in_progress: ("in progress", "in-progress", "ongoing"),
    TicketStatus.waiting_for_customer: ("waiting for customer",),
    TicketStatus.waiting_for_support_vendor: ("waiting for vendor", "waiting for support/vendor", "pending"),
    TicketStatus.pending: ("pending", "waiting"),
    TicketStatus.resolved: ("resolved", "done"),
    TicketStatus.closed: ("closed",),
}

REQUEST_TYPE_NAME_BY_TICKET_TYPE: dict[TicketType, tuple[str, ...]] = {
    TicketType.incident: (
        "Report a system problem",
        "Report broken hardware",
    ),
    TicketType.service_request: (
        "Emailed request",
        "Get IT help",
        "Request a new account",
        "Request admin access",
        "Request new software",
        "Request new hardware",
        "Onboard new employees",
    ),
}
REQUEST_TYPE_NAME_BY_CATEGORY_AND_TYPE: dict[TicketType, dict[str, tuple[str, ...]]] = {
    TicketType.incident: {
        "hardware": ("Report broken hardware", "Report a system problem"),
        "problem": ("Report a system problem",),
        "application": ("Report a system problem",),
        "network": ("Report a system problem",),
        "infrastructure": ("Report a system problem",),
        "security": ("Report a system problem",),
        "email": ("Report a system problem",),
        "service_request": ("Report a system problem",),
    },
    TicketType.service_request: {
        "hardware": ("Request new hardware", "Get IT help"),
        "application": ("Request new software", "Get IT help"),
        "security": ("Request admin access", "Get IT help"),
        "email": ("Emailed request", "Get IT help"),
        "service_request": ("Emailed request", "Get IT help"),
        "problem": ("Get IT help",),
        "network": ("Get IT help",),
        "infrastructure": ("Get IT help",),
    },
}
CATEGORY_COMPONENT_NAME_BY_CATEGORY: dict[TicketCategory, str] = {
    TicketCategory.application: "Application",
    TicketCategory.email: "Email",
    TicketCategory.hardware: "Hardware",
    TicketCategory.infrastructure: "Infrastructure",
    TicketCategory.network: "Network",
    TicketCategory.problem: "Problem",
    TicketCategory.security: "Security",
    TicketCategory.service_request: "Service Request",
}
CATEGORY_COMPONENT_DESCRIPTION_PREFIX = "Managed by TeamWill ITSM category sync."


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ticket_type(ticket: Ticket) -> TicketType:
    value = getattr(ticket, "ticket_type", None)
    return value or TicketType.service_request


def _request_type_field_key() -> str:
    value = str(settings.JIRA_REQUEST_TYPE_FIELD or "").strip()
    return value or "customfield_10010"


def _jira_ready() -> bool:
    return settings.jira_ready


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


def _resolve_issue_type_id(client: JiraClient, project_key: str, ticket_type: TicketType | None = None) -> str | None:
    try:
        payload = client._request("GET", f"/rest/api/3/project/{project_key}")  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira issue type resolution failed: %s", exc)
        return None
    issue_types = [item for item in list(payload.get("issueTypes") or []) if isinstance(item, dict)]
    if not issue_types:
        return None

    return _select_issue_type_id(issue_types, ticket_type=ticket_type)


def _select_issue_type_id(issue_types: list[dict[str, Any]], ticket_type: TicketType | None = None) -> str | None:
    by_name = {str(item.get("name") or "").strip().casefold(): item for item in issue_types}
    target_type = ticket_type or TicketType.service_request
    for name in PREFERRED_ISSUE_TYPES_BY_TICKET_TYPE.get(target_type, ()):
        matched = by_name.get(name.casefold())
        if matched and str(matched.get("id") or "").strip():
            return str(matched.get("id")).strip()

    fallback = issue_types[0] if issue_types else {}
    issue_type_id = str(fallback.get("id") or "").strip()
    return issue_type_id or None


def _resolve_priority_name(priority: TicketPriority) -> str:
    return PRIORITY_TO_JIRA.get(priority, "Medium")


def _labels(ticket: Ticket) -> list[str]:
    labels = [
        "local-itsm",
        f"local_{ticket.id.lower().replace('-', '_')}",
        f"priority_{ticket.priority.value}",
        f"ticket_type_{_ticket_type(ticket).value}",
        f"{CATEGORY_LABEL_PREFIX}{ticket.category.value}",
    ]
    assignee_slug = _slug(ticket.assignee)
    if assignee_slug and ticket.assignee.strip().lower() != "unassigned":
        labels.append(f"{LOCAL_ASSIGNEE_LABEL_PREFIX}{assignee_slug}")
    reporter_slug = _slug(ticket.reporter)
    if reporter_slug:
        labels.append(f"{LOCAL_REPORTER_LABEL_PREFIX}{reporter_slug}")
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


def _summary_title(ticket: Ticket) -> str:
    cleaned = normalize_local_ticket_title(ticket.title)
    id_prefix = re.compile(rf"^\[{re.escape(ticket.id)}\]\s*", re.IGNORECASE)
    cleaned = id_prefix.sub("", cleaned, count=1).strip() or cleaned
    return cleaned or f"Ticket {ticket.id}"


def _category_component_name(category: TicketCategory) -> str:
    return CATEGORY_COMPONENT_NAME_BY_CATEGORY.get(category, "Service Request")


def _category_component_description(category: TicketCategory) -> str:
    return f"{CATEGORY_COMPONENT_DESCRIPTION_PREFIX} Local category: {category.value}."


def _identity(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _slug(value: str | None) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:48]


def _lookup_local_user_identity(user_value: str | None) -> tuple[str | None, str | None]:
    raw = str(user_value or "").strip()
    if not raw:
        return None, None

    with SessionLocal() as db:
        if "@" in raw:
            user = db.query(User).filter(User.email.ilike(raw)).first()
            if user:
                return str(user.name or "").strip() or raw, str(user.email or "").strip() or raw
            return None, raw

        user = db.query(User).filter(User.name.ilike(raw)).first()
        if user:
            return str(user.name or "").strip() or raw, str(user.email or "").strip() or None

    return raw, None


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


def _find_best_account_id(
    client: JiraClient,
    *,
    raw: str,
    queries: list[str],
    assignable: bool,
    project_key: str | None = None,
) -> str | None:
    if not raw:
        return None

    raw_identity = _identity(raw)
    best_fallback: str | None = None

    for query in queries:
        try:
            users = (
                client.search_assignable_users(query, project_key=project_key, max_results=20)
                if assignable
                else client.search_users(query, max_results=20)
            )
        except Exception as exc:  # noqa: BLE001
            search_kind = "assignable user" if assignable else "user"
            logger.warning("Jira %s search failed for query '%s': %s", search_kind, query, exc)
            continue
        if not users:
            continue

        for user in users:
            account_id = str(user.get("accountId") or user.get("id") or "").strip()
            if not account_id:
                continue
            if not bool(user.get("active", True)):
                continue
            if assignable and str(user.get("accountType") or "").strip().lower() == "customer":
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


def _resolve_user_account_id(
    client: JiraClient,
    user_value: str | None,
    *,
    assignable: bool = False,
    project_key: str | None = None,
    ensure_customer: bool = False,
) -> str | None:
    display_name, email = _lookup_local_user_identity(user_value)
    raw = str(email or display_name or user_value or "").strip()
    if not raw:
        return None

    synced_account_id: str | None = None
    if project_key:
        try:
            synced_account_id = sync_jira_project_roles_for_identity(
                raw,
                client=client,
                project_key=project_key,
            )
            if synced_account_id and not assignable:
                return synced_account_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira role sync failed for '%s': %s", raw, exc)

    queries = [*_candidate_queries(email), *_candidate_queries(display_name), *_candidate_queries(raw)]
    deduped_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped_queries.append(query)

    account_id = _find_best_account_id(
        client,
        raw=raw,
        queries=deduped_queries,
        assignable=assignable,
        project_key=project_key,
    )
    if account_id:
        return account_id
    if account_id or assignable or not ensure_customer or not email:
        return account_id

    try:
        created = client.create_customer(display_name=display_name or raw, email=email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira customer create failed for '%s' (%s): %s", display_name or raw, email, exc)
        return None

    created_account_id = str(created.get("accountId") or created.get("id") or "").strip()
    if created_account_id:
        return created_account_id

    refreshed_queries = [*_candidate_queries(email), *_candidate_queries(display_name), *_candidate_queries(raw)]
    return _find_best_account_id(
        client,
        raw=raw,
        queries=refreshed_queries,
        assignable=False,
        project_key=project_key,
    )


def _jira_user_field(account_id: str | None) -> dict[str, str] | None:
    value = (account_id or "").strip()
    if not value:
        return None
    return {"accountId": value}


def _assignee_field_for_ticket(
    client: JiraClient,
    assignee_value: str | None,
    *,
    project_key: str | None = None,
) -> tuple[dict[str, str] | None, bool]:
    raw = str(assignee_value or "").strip()
    if not raw or raw.lower() == "unassigned":
        return None, False

    account_id = _resolve_user_account_id(client, raw, assignable=True, project_key=project_key)
    if not account_id:
        return None, True
    return _jira_user_field(account_id), False


def _resolve_service_desk_id(client: JiraClient, project_key: str) -> str | None:
    configured = str(settings.JIRA_SERVICE_DESK_ID or "").strip()
    if configured:
        return configured

    target = (project_key or "").strip().casefold()
    if not target:
        return None

    for desk in client.get_service_desks():
        project = str(desk.get("projectKey") or "").strip().casefold()
        if project != target:
            continue
        desk_id = str(desk.get("id") or "").strip()
        if desk_id:
            return desk_id
    return None


def _resolve_category_component_id(client: JiraClient, project_key: str, category: TicketCategory) -> str | None:
    component_name = _category_component_name(category)
    if not component_name:
        return None

    try:
        components = client.get_project_components(project_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira component list failed for %s: %s", project_key, exc)
        return None

    for component in components:
        name = str(component.get("name") or "").strip()
        component_id = str(component.get("id") or "").strip()
        if name.casefold() == component_name.casefold() and component_id:
            return component_id

    try:
        created = client.create_project_component(
            project_key=project_key,
            name=component_name,
            description=_category_component_description(category),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira component create failed for %s/%s: %s", project_key, component_name, exc)
        return None

    component_id = str(created.get("id") or "").strip()
    return component_id or None


def _request_type_keywords(ticket: Ticket) -> list[str]:
    haystack = " ".join(
        part for part in [ticket.title or "", ticket.description or "", " ".join(ticket.tags or [])] if part
    ).casefold()
    keywords: list[str] = []
    if any(token in haystack for token in {"admin access", "administrator access", "privileged access"}):
        keywords.append("Request admin access")
    if any(token in haystack for token in {"new account", "create account", "account access"}):
        keywords.append("Request a new account")
    if any(token in haystack for token in {"hardware", "laptop", "desktop", "screen", "keyboard", "mouse"}):
        keywords.extend(["Report broken hardware", "Request new hardware"])
    if any(token in haystack for token in {"software", "application", "app install", "install"}):
        keywords.append("Request new software")
    if _ticket_type(ticket) == TicketType.incident or any(token in haystack for token in {"incident", "outage", "error", "failure", "problem"}):
        keywords.append("Report a system problem")
    return keywords


def _request_type_candidates_for_ticket(ticket: Ticket) -> list[str]:
    resolved_ticket_type = _ticket_type(ticket)
    ticket_type_names = REQUEST_TYPE_NAME_BY_TICKET_TYPE.get(resolved_ticket_type, ())
    category_names = REQUEST_TYPE_NAME_BY_CATEGORY_AND_TYPE.get(resolved_ticket_type, {}).get(ticket.category.value, ())
    return [*category_names, *_request_type_keywords(ticket), *ticket_type_names]


def _request_type_issue_type_ids(request_types: list[dict[str, Any]], ticket_type: TicketType) -> set[str]:
    desired_names = {
        name.casefold()
        for name in REQUEST_TYPE_NAME_BY_TICKET_TYPE.get(ticket_type, ())
    }
    ids: set[str] = set()
    for request_type in request_types:
        name = str(request_type.get("name") or "").strip().casefold()
        issue_type_id = str(request_type.get("issueTypeId") or "").strip()
        if name in desired_names and issue_type_id:
            ids.add(issue_type_id)
    return ids


def _preferred_request_type_names(ticket: Ticket) -> list[str]:
    names: list[str] = []
    names.extend(_request_type_candidates_for_ticket(ticket))
    configured = str(settings.JIRA_DEFAULT_REQUEST_TYPE_NAME or "").strip()
    if configured:
        names.append(configured)
    if _ticket_type(ticket) == TicketType.incident:
        names.extend(["Report a system problem", "Report broken hardware"])
    else:
        names.extend(["Emailed request", "Get IT help"])

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = name.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _select_request_type(request_types: list[dict[str, Any]], ticket: Ticket) -> dict[str, Any] | None:
    if not request_types:
        return None

    desired_issue_type_ids = _request_type_issue_type_ids(request_types, _ticket_type(ticket))
    candidate_request_types = [
        request_type
        for request_type in request_types
        if not desired_issue_type_ids or str(request_type.get("issueTypeId") or "").strip() in desired_issue_type_ids
    ] or request_types

    configured_id = str(settings.JIRA_DEFAULT_REQUEST_TYPE_ID or "").strip()
    if configured_id:
        for request_type in candidate_request_types:
            if str(request_type.get("id") or "").strip() == configured_id:
                return request_type

    by_name = {str(item.get("name") or "").strip().casefold(): item for item in candidate_request_types}
    for name in _preferred_request_type_names(ticket):
        matched = by_name.get(name.casefold())
        if matched is not None:
            return matched

    return candidate_request_types[0]


def _resolve_request_type_id(client: JiraClient, project_key: str, ticket: Ticket) -> str | None:
    service_desk_id = _resolve_service_desk_id(client, project_key)
    if not service_desk_id:
        return None
    request_type = _select_request_type(client.get_request_types(service_desk_id), ticket)
    request_type_id = str((request_type or {}).get("id") or "").strip()
    return request_type_id or None


def _request_field_values(ticket: Ticket) -> dict[str, Any]:
    values = {
        "summary": f"[{ticket.id}] {_summary_title(ticket)}"[:255],
        "description": _description(ticket)[:4000],
    }
    due_at = getattr(ticket, "due_at", None)
    if due_at is not None:
        values["duedate"] = due_at.date().isoformat()
    return values


def _issue_update_payload(
    ticket: Ticket,
    *,
    client: JiraClient | None = None,
    project_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": f"[{ticket.id}] {_summary_title(ticket)}"[:255],
        "description": _adf_from_text(_description(ticket)),
        "labels": _labels(ticket),
        "priority": {"name": _resolve_priority_name(ticket.priority)},
    }
    due_at = getattr(ticket, "due_at", None)
    if due_at is not None:
        payload["duedate"] = due_at.date().isoformat()
    else:
        payload["duedate"] = None
    if client is not None and project_key:
        component_id = _resolve_category_component_id(client, project_key, ticket.category)
        if component_id:
            payload["components"] = [{"id": component_id}]
    return payload


def _format_comment_text_for_jira(
    comment_text: str,
    *,
    author_name: str | None = None,
    jira_actor_name: str | None = None,
) -> str:
    normalized = (comment_text or "").strip()
    if not normalized:
        return ""

    author = str(author_name or "").strip()
    jira_actor = str(jira_actor_name or "").strip()
    if author and _identity(author) not in {"", _identity(jira_actor)}:
        return f"[Platform author: {author}]\n\n{normalized}"
    return normalized


def _update_issue_with_retries(client: JiraClient, issue_key: str, ticket: Ticket, *, project_key: str | None = None) -> bool:
    update_payload = _issue_update_payload(ticket, client=client, project_key=project_key)
    assignee_field, assignee_unavailable = _assignee_field_for_ticket(
        client,
        ticket.assignee,
        project_key=project_key,
    )
    if assignee_field:
        update_payload["assignee"] = assignee_field
    elif assignee_unavailable:
        update_payload["assignee"] = None
    reporter_field = _jira_user_field(
        _resolve_user_account_id(client, ticket.reporter, project_key=project_key, ensure_customer=True)
    )
    if reporter_field:
        update_payload["reporter"] = reporter_field
    resolved_project_key = project_key or _project_key_from_issue_key(issue_key)
    if resolved_project_key:
        request_type_id = _resolve_request_type_id(client, resolved_project_key, ticket)
        if request_type_id:
            update_payload[_request_type_field_key()] = request_type_id

    attempts: list[dict[str, Any]] = [
        update_payload,
        {key: value for key, value in update_payload.items() if key not in {"reporter"}},
        {key: value for key, value in update_payload.items() if key not in {"reporter", "assignee"}},
    ]
    for index, payload in enumerate(attempts, start=1):
        try:
            client.update_issue_fields(issue_key, payload)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira issue update attempt %s failed for %s: %s", index, ticket.id, exc)
    return False


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
        **_issue_update_payload(ticket, client=client, project_key=project_key),
    }
    assignee_field, assignee_unavailable = _assignee_field_for_ticket(
        client,
        ticket.assignee,
        project_key=project_key,
    )
    if assignee_field:
        fields["assignee"] = assignee_field
    elif assignee_unavailable:
        fields["assignee"] = None
    reporter_field = _jira_user_field(
        _resolve_user_account_id(client, ticket.reporter, project_key=project_key, ensure_customer=True)
    )
    if reporter_field:
        fields["reporter"] = reporter_field
    request_type_id = _resolve_request_type_id(client, project_key, ticket)
    if request_type_id:
        fields[_request_type_field_key()] = request_type_id
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

    service_desk_id = _resolve_service_desk_id(client, project_key)
    if service_desk_id:
        request_types = _select_request_type(client.get_request_types(service_desk_id), ticket)
        if request_types is not None:
            request_type_id = str(request_types.get("id") or "").strip()
            if request_type_id:
                try:
                    _resolve_user_account_id(client, ticket.reporter, project_key=project_key, ensure_customer=True)
                    _reporter_name, reporter_email = _lookup_local_user_identity(ticket.reporter)
                    created_request = client.create_customer_request(
                        service_desk_id=service_desk_id,
                        request_type_id=request_type_id,
                        request_field_values=_request_field_values(ticket),
                        raise_on_behalf_of=reporter_email,
                    )
                    issue_key = str(created_request.get("issueKey") or "").strip()
                    if issue_key:
                        _update_issue_with_retries(client, issue_key, ticket, project_key=project_key)
                        return issue_key
                except Exception as exc:  # noqa: BLE001
                    logger.warning("JSM customer request create failed for %s: %s", ticket.id, exc)

    issue_type_id = _resolve_issue_type_id(client, project_key, _ticket_type(ticket))
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
    updated = _update_issue_with_retries(client, issue_key, ticket, project_key=project_key)

    status_changed = _sync_issue_status(client, ticket)
    return updated or status_changed


def add_jira_comment_for_ticket(ticket: Ticket, comment_text: str, *, author_name: str | None = None) -> bool:
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
        jira_actor_name = str((client.get_myself() or {}).get("displayName") or "").strip()
        rendered = _format_comment_text_for_jira(
            normalized,
            author_name=author_name,
            jira_actor_name=jira_actor_name,
        )
        return client.add_issue_comment(issue_key, _adf_from_text(rendered))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira comment push failed for %s: %s", ticket.id, exc)
        return False
