"""Bulk-import local tickets and comments into Jira via REST API.

Usage examples (PowerShell):

    python scripts\\jira_bulk_import.py --limit 50
    python scripts\\jira_bulk_import.py --limit 200 --apply
    python scripts\\jira_bulk_import.py --apply --issue-type "Incident"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import selectinload

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import TicketPriority, TicketStatus, UserRole  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.models.user import User  # noqa: E402

SEARCH_JQL_PATH = "/rest/api/3/search/jql"
PROJECT_PATH = "/rest/api/3/project/{project_key}"
PRIORITIES_PATH = "/rest/api/3/priority"
CREATEMETA_ISSUETYPE_PATH = "/rest/api/3/issue/createmeta/{project_key}/issuetypes/{issue_type_id}"
CREATE_ISSUE_PATH = "/rest/api/3/issue"
CREATE_COMMENT_PATH = "/rest/api/3/issue/{issue_key}/comment"
ISSUE_PATH = "/rest/api/3/issue/{issue_key}"
USER_SEARCH_PATH = "/rest/api/3/user/search"
CREATE_USER_PATH = "/rest/api/3/user"
PROJECT_ROLES_PATH = "/rest/api/3/project/{project_key}/role"
MAX_SUMMARY_LEN = 255
MAX_LABELS = 12
SOURCE_LABEL = "source_local_itsm"
SEED_LABEL_PREFIX = "twseed_"

LABEL_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")

PRIORITY_TO_JIRA = {
    TicketPriority.critical: "Highest",
    TicketPriority.high: "High",
    TicketPriority.medium: "Medium",
    TicketPriority.low: "Low",
}

PRIORITY_TO_URGENCY_CANDIDATES = {
    TicketPriority.critical: ["critical", "highest", "high"],
    TicketPriority.high: ["high", "major"],
    TicketPriority.medium: ["medium", "moderate"],
    TicketPriority.low: ["low", "minor"],
}

PRIORITY_TO_IMPACT_CANDIDATES = {
    TicketPriority.critical: ["extensive / widespread", "extensive", "major"],
    TicketPriority.high: ["significant / large", "significant", "large"],
    TicketPriority.medium: ["moderate / limited", "moderate", "limited"],
    TicketPriority.low: ["minor / localized", "minor", "localized"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk-import local tickets/comments into Jira")
    parser.add_argument("--apply", action="store_true", help="Actually create issues/comments in Jira")
    parser.add_argument("--limit", type=int, default=120, help="Max number of local tickets to process")
    parser.add_argument("--project-key", default="", help="Override Jira project key (else JIRA_PROJECT_KEY)")
    parser.add_argument("--issue-type", default="", help="Preferred Jira issue type name (e.g. Incident)")
    parser.add_argument("--max-comments", type=int, default=8, help="Max comments imported per ticket")
    parser.add_argument("--sleep-ms", type=int, default=80, help="Delay between write requests (ms)")
    parser.add_argument(
        "--user-products",
        default="jira-servicedesk",
        help="Comma-separated Jira products for created users (default: jira-servicedesk)",
    )
    parser.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        default=True,
        help="Skip tickets already imported (default: true)",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Do not skip already imported tickets",
    )
    parser.add_argument(
        "--sync-users",
        dest="sync_users",
        action="store_true",
        default=True,
        help="Create/sync local users to Jira before importing tickets (default: true)",
    )
    parser.add_argument(
        "--no-sync-users",
        dest="sync_users",
        action="store_false",
        help="Disable Jira user sync",
    )
    parser.add_argument(
        "--auto-assign",
        dest="auto_assign",
        action="store_true",
        default=True,
        help="Auto-assign tickets in Jira when assignee is missing/unmapped (default: true)",
    )
    parser.add_argument(
        "--no-auto-assign",
        dest="auto_assign",
        action="store_false",
        help="Disable Jira auto-assignment fallback",
    )
    parser.add_argument(
        "--update-existing",
        dest="update_existing",
        action="store_true",
        default=True,
        help="Update existing imported Jira issues instead of skipping (default: true)",
    )
    parser.add_argument(
        "--no-update-existing",
        dest="update_existing",
        action="store_false",
        help="Skip existing imported issues without updating them",
    )
    return parser.parse_args()


def _sanitize_label(value: str) -> str:
    cleaned = LABEL_SAFE_RE.sub("_", (value or "").strip().lower()).strip("_")
    return cleaned[:255]


def _seed_label(ticket_id: str) -> str:
    ticket_part = _sanitize_label(ticket_id)
    return f"{SEED_LABEL_PREFIX}{ticket_part}"[:255]


def _truncate(text: str, *, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _adf_from_text(text: str) -> dict[str, Any]:
    paragraphs = []
    for line in (text or "").splitlines():
        clean = line.strip()
        if not clean:
            continue
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": clean[:32000]}],
            }
        )
    if not paragraphs:
        paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": "-"}]}]
    return {"type": "doc", "version": 1, "content": paragraphs}


def _jira_get(client: httpx.Client, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{settings.JIRA_BASE_URL.rstrip('/')}{path}"
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _jira_post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.JIRA_BASE_URL.rstrip('/')}{path}"
    response = client.post(url, json=payload)
    response.raise_for_status()
    return response.json()


def _jira_put(client: httpx.Client, path: str, payload: dict[str, Any]) -> None:
    url = f"{settings.JIRA_BASE_URL.rstrip('/')}{path}"
    response = client.put(url, json=payload)
    if response.status_code not in (200, 204):
        response.raise_for_status()


def _resolve_issue_type(client: httpx.Client, project_key: str, preferred_name: str | None) -> dict[str, str]:
    data = _jira_get(client, PROJECT_PATH.format(project_key=project_key))
    issue_types = [it for it in (data.get("issueTypes") or []) if not it.get("subtask")]
    if not issue_types:
        raise RuntimeError(f"No issue types available for project {project_key}")

    preferred = (preferred_name or "").strip().lower()
    if preferred:
        for it in issue_types:
            if str(it.get("name", "")).strip().lower() == preferred:
                return {"id": str(it["id"]), "name": str(it["name"])}

    preferred_order = ["Report an incident", "Incident", "Task", "Service Request", "Story", "Bug"]
    by_name = {str(it.get("name")): it for it in issue_types}
    for name in preferred_order:
        if name in by_name:
            choice = by_name[name]
            return {"id": str(choice["id"]), "name": str(choice["name"])}

    fallback = issue_types[0]
    return {"id": str(fallback["id"]), "name": str(fallback["name"])}


def _fetch_priority_names(client: httpx.Client) -> set[str]:
    data = _jira_get(client, PRIORITIES_PATH)
    if isinstance(data, list):
        return {str(item.get("name", "")).strip() for item in data if item.get("name")}
    return set()


def _simplify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _fetch_createmeta_fields(client: httpx.Client, project_key: str, issue_type_id: str) -> list[dict[str, Any]]:
    data = _jira_get(
        client,
        CREATEMETA_ISSUETYPE_PATH.format(project_key=project_key, issue_type_id=issue_type_id),
        params={"expand": "fields"},
    )
    return list(data.get("fields") or [])


def _extract_select_field(fields: list[dict[str, Any]], field_name: str) -> dict[str, Any] | None:
    target = field_name.strip().lower()
    for field in fields:
        name = str(field.get("name") or "").strip().lower()
        if name != target:
            continue
        field_id = str(field.get("fieldId") or field.get("key") or "").strip()
        if not field_id:
            continue
        schema = field.get("schema") or {}
        field_type = str(schema.get("type") or "")
        allowed_values = [str(v.get("value") or "").strip() for v in (field.get("allowedValues") or []) if v.get("value")]
        return {
            "field_id": field_id,
            "field_type": field_type,
            "allowed_values": allowed_values,
        }
    return None


def _pick_allowed_value(allowed_values: list[str], candidates: list[str]) -> str | None:
    if not allowed_values:
        return None
    normalized_map = {_simplify(value): value for value in allowed_values}
    for candidate in candidates:
        key = _simplify(candidate)
        if key in normalized_map:
            return normalized_map[key]
    for candidate in candidates:
        key = _simplify(candidate)
        for normalized, original in normalized_map.items():
            if key and (key in normalized or normalized in key):
                return original
    return None


def _build_urgency_impact_fields(
    *,
    local_priority: TicketPriority,
    urgency_field: dict[str, Any] | None,
    impact_field: dict[str, Any] | None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    if urgency_field:
        urgency_value = _pick_allowed_value(
            list(urgency_field.get("allowed_values") or []),
            PRIORITY_TO_URGENCY_CANDIDATES.get(local_priority, []),
        )
        if urgency_value:
            fields[str(urgency_field["field_id"])] = {"value": urgency_value}

    if impact_field:
        impact_value = _pick_allowed_value(
            list(impact_field.get("allowed_values") or []),
            PRIORITY_TO_IMPACT_CANDIDATES.get(local_priority, []),
        )
        if impact_value:
            fields[str(impact_field["field_id"])] = {"value": impact_value}

    return fields


def _parse_user_products(raw: str) -> list[str]:
    values = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return values or ["jira-servicedesk"]


def _fetch_project_role_urls(client: httpx.Client, project_key: str) -> dict[str, str]:
    data = _jira_get(client, PROJECT_ROLES_PATH.format(project_key=project_key))
    if not isinstance(data, dict):
        return {}
    return {str(name): str(url) for name, url in data.items() if isinstance(url, str)}


def _pick_agent_role_url(role_urls: dict[str, str]) -> str | None:
    preferred_names = ["Agent", "Service Desk Team", "Service Desk Agents", "Administrator"]
    normalized = {name.strip().lower(): url for name, url in role_urls.items()}
    for name in preferred_names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def _search_jira_users(client: httpx.Client, query: str, *, max_results: int = 20) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    data = _jira_get(
        client,
        USER_SEARCH_PATH,
        params={"query": query.strip(), "maxResults": max_results},
    )
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _find_user_account_id(client: httpx.Client, *, name: str, email: str) -> str | None:
    candidates = [email, name, email.split("@", 1)[0] if "@" in email else ""]
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        users = _search_jira_users(client, candidate)
        if not users:
            continue

        email_lower = email.strip().lower()
        name_lower = name.strip().lower()
        for user in users:
            account_id = str(user.get("accountId") or "").strip()
            if not account_id:
                continue
            user_email = str(user.get("emailAddress") or "").strip().lower()
            user_name = str(user.get("displayName") or "").strip().lower()
            if user_email and user_email == email_lower:
                return account_id
            if user_name and user_name == name_lower:
                return account_id

        first_account = str(users[0].get("accountId") or "").strip()
        if first_account:
            return first_account
    return None


def _create_jira_user(client: httpx.Client, *, name: str, email: str, products: list[str]) -> str | None:
    payload = {
        "emailAddress": email.strip(),
        "displayName": name.strip() or email.strip(),
        "products": products,
    }
    response = client.post(f"{settings.JIRA_BASE_URL.rstrip('/')}{CREATE_USER_PATH}", json=payload)
    if response.status_code in (200, 201):
        data = response.json()
        return str(data.get("accountId") or "").strip() or None
    if response.status_code == 409:
        return _find_user_account_id(client, name=name, email=email)
    if response.status_code == 400 and "already" in response.text.lower():
        return _find_user_account_id(client, name=name, email=email)
    if response.status_code in (400, 403):
        # Permission or payload constraints; caller handles fallback.
        return None
    response.raise_for_status()
    return None


def _add_user_to_project_role(client: httpx.Client, role_url: str, account_id: str) -> bool:
    if not role_url or not account_id:
        return False
    response = client.post(role_url, json={"user": [account_id]})
    if response.status_code in (200, 201, 204):
        return True
    if response.status_code == 400 and "already" in response.text.lower():
        return True
    if response.status_code in (403, 404):
        return False
    response.raise_for_status()
    return False


def _get_myself_account_id(client: httpx.Client) -> str | None:
    data = _jira_get(client, "/rest/api/3/myself")
    if not isinstance(data, dict):
        return None
    account_id = str(data.get("accountId") or "").strip()
    return account_id or None


def _sync_local_users_to_jira(
    client: httpx.Client,
    *,
    project_key: str,
    local_users: list[dict[str, str]],
    products: list[str],
    allow_create: bool,
) -> tuple[dict[str, str], list[str]]:
    role_urls = _fetch_project_role_urls(client, project_key)
    agent_role_url = _pick_agent_role_url(role_urls)

    name_to_account: dict[str, str] = {}
    assignment_pool: list[str] = []
    assignment_set: set[str] = set()

    created = 0
    existing = 0
    role_added = 0

    for user in local_users:
        name = str(user.get("name") or "").strip()
        email = str(user.get("email") or "").strip().lower()
        role = str(user.get("role") or "").strip().lower()
        if not name or not email:
            continue

        account_id = _find_user_account_id(client, name=name, email=email)
        if account_id:
            existing += 1
        elif allow_create:
            account_id = _create_jira_user(client, name=name, email=email, products=products)
            if account_id:
                created += 1

        if not account_id:
            continue

        if role in {"admin", "agent"} and agent_role_url and allow_create:
            if _add_user_to_project_role(client, agent_role_url, account_id):
                role_added += 1

        name_to_account[name] = account_id
        if role in {"admin", "agent"} and account_id not in assignment_set:
            assignment_set.add(account_id)
            assignment_pool.append(account_id)

    myself = _get_myself_account_id(client)
    if myself and myself not in assignment_set:
        assignment_set.add(myself)
        assignment_pool.append(myself)

    print(f"User sync: existing={existing}, created={created}, role_updates={role_added}, assignable_pool={len(assignment_pool)}")
    return name_to_account, assignment_pool


def _detect_project_key(client: httpx.Client) -> str:
    data = _jira_get(
        client,
        SEARCH_JQL_PATH,
        params={
            "jql": "updated IS NOT EMPTY ORDER BY updated DESC",
            "fields": "key",
            "maxResults": 1,
            "startAt": 0,
        },
    )
    issues = list(data.get("issues") or [])
    if not issues:
        return ""
    key = str(issues[0].get("key") or "").strip()
    if "-" not in key:
        return ""
    return key.split("-", 1)[0]


def _resolve_priority_name(local_priority: TicketPriority, available: set[str]) -> str | None:
    target = PRIORITY_TO_JIRA.get(local_priority)
    if not target:
        return None
    lower_available = {name.lower(): name for name in available}
    if target.lower() in lower_available:
        return lower_available[target.lower()]
    return None


def _fetch_existing_seed_issues(client: httpx.Client, project_key: str) -> dict[str, str]:
    seed_to_issue: dict[str, str] = {}
    start_at = 0
    while True:
        data = _jira_get(
            client,
            SEARCH_JQL_PATH,
            params={
                "jql": f'project = "{project_key}" AND labels IS NOT EMPTY ORDER BY created DESC',
                "fields": "labels",
                "maxResults": 100,
                "startAt": start_at,
            },
        )
        issues = list(data.get("issues") or [])
        if not issues:
            break
        for issue in issues:
            issue_key = str(issue.get("key") or "").strip()
            if not issue_key:
                continue
            fields = issue.get("fields") or {}
            for label in fields.get("labels") or []:
                label_text = str(label)
                if label_text.startswith(SEED_LABEL_PREFIX):
                    seed_to_issue[label_text] = issue_key
        start_at += len(issues)
        total = int(data.get("total") or 0)
        if start_at >= total:
            break
    return seed_to_issue


def _build_description(ticket: Ticket) -> str:
    lines = [
        "Imported from local ITSM platform",
        f"Local ticket ID: {ticket.id}",
        f"Reporter: {ticket.reporter}",
        f"Assignee: {ticket.assignee}",
        "",
        (ticket.description or "").strip(),
    ]
    if ticket.resolution:
        lines.extend(["", "Local resolution:", ticket.resolution.strip()])
    return "\n".join(lines).strip()


def _build_labels(ticket: Ticket) -> list[str]:
    labels = [
        SOURCE_LABEL,
        _seed_label(ticket.id),
        _sanitize_label(f"status_{ticket.status.value}"),
        _sanitize_label(f"category_{ticket.category.value}"),
        _sanitize_label(f"priority_{ticket.priority.value}"),
    ]
    for tag in ticket.tags or []:
        sanitized = _sanitize_label(str(tag))
        if sanitized:
            labels.append(sanitized)

    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if not label or label in seen:
            continue
        seen.add(label)
        deduped.append(label)
        if len(deduped) >= MAX_LABELS:
            break
    return deduped


def _comment_text(comment: Any) -> str:
    author = getattr(comment, "author", "") or "Unknown"
    created_at = getattr(comment, "created_at", None)
    created = created_at.isoformat() if created_at else ""
    content = (getattr(comment, "content", "") or "").strip()
    header = f"[Local comment | author={author} | created={created}]"
    return f"{header}\n{content}".strip()


def _resolution_comment_text(ticket: Ticket) -> str | None:
    if not ticket.resolution:
        return None
    if ticket.status not in {TicketStatus.resolved, TicketStatus.closed}:
        return None
    return f"[Local resolution]\n{ticket.resolution.strip()}"


def _load_local_users() -> list[dict[str, str]]:
    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.role.in_([UserRole.admin, UserRole.agent]))
            .order_by(User.created_at.asc())
            .all()
        )
        return [
            {
                "name": str(user.name or "").strip(),
                "email": str(user.email or "").strip().lower(),
                "role": str(user.role.value if hasattr(user.role, "value") else user.role),
            }
            for user in users
            if user.name and user.email
        ]
    finally:
        db.close()


def _create_issue(
    client: httpx.Client,
    *,
    project_key: str,
    issue_type_id: str,
    ticket: Ticket,
    jira_priority_name: str | None,
    assignee_account_id: str | None,
    extra_fields: dict[str, Any] | None = None,
) -> str:
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": issue_type_id},
        "summary": _truncate(f"[{ticket.id}] {ticket.title}", max_len=MAX_SUMMARY_LEN),
        "description": _adf_from_text(_build_description(ticket)),
        "labels": _build_labels(ticket),
    }
    if jira_priority_name:
        fields["priority"] = {"name": jira_priority_name}
    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}
    if extra_fields:
        fields.update(extra_fields)
    created = _jira_post(client, CREATE_ISSUE_PATH, {"fields": fields})
    issue_key = str(created.get("key") or "").strip()
    if not issue_key:
        raise RuntimeError(f"Issue creation returned no key: {json.dumps(created)}")
    return issue_key


def _update_issue(
    client: httpx.Client,
    *,
    issue_key: str,
    ticket: Ticket,
    jira_priority_name: str | None,
    assignee_account_id: str | None,
    extra_fields: dict[str, Any] | None = None,
) -> None:
    fields: dict[str, Any] = {
        "summary": _truncate(f"[{ticket.id}] {ticket.title}", max_len=MAX_SUMMARY_LEN),
        "description": _adf_from_text(_build_description(ticket)),
        "labels": _build_labels(ticket),
    }
    if jira_priority_name:
        fields["priority"] = {"name": jira_priority_name}
    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}
    if extra_fields:
        fields.update(extra_fields)
    _jira_put(client, ISSUE_PATH.format(issue_key=issue_key), {"fields": fields})


def _add_comments(client: httpx.Client, issue_key: str, ticket: Ticket, *, max_comments: int, sleep_seconds: float) -> int:
    count = 0
    sorted_comments = sorted(ticket.comments or [], key=lambda c: c.created_at)[: max(0, max_comments)]
    for comment in sorted_comments:
        text = _comment_text(comment)
        if not text:
            continue
        _jira_post(
            client,
            CREATE_COMMENT_PATH.format(issue_key=issue_key),
            {"body": _adf_from_text(text)},
        )
        count += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    resolution_text = _resolution_comment_text(ticket)
    if resolution_text:
        _jira_post(
            client,
            CREATE_COMMENT_PATH.format(issue_key=issue_key),
            {"body": _adf_from_text(resolution_text)},
        )
        count += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return count


def main() -> int:
    args = parse_args()
    project_key = (args.project_key or settings.JIRA_PROJECT_KEY).strip()

    if not settings.JIRA_BASE_URL.strip() or not settings.JIRA_EMAIL.strip() or not settings.JIRA_API_TOKEN.strip():
        print("Missing Jira credentials. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in backend/.env")
        return 1

    db = SessionLocal()
    try:
        query = (
            db.query(Ticket)
            .options(selectinload(Ticket.comments))
            .order_by(Ticket.created_at.asc())
        )
        if args.limit and args.limit > 0:
            query = query.limit(args.limit)
        tickets = list(query.all())
    finally:
        db.close()

    if not tickets:
        print("No local tickets found to import.")
        return 0

    local_users = _load_local_users()
    sleep_seconds = max(args.sleep_ms, 0) / 1000.0

    with httpx.Client(
        timeout=30,
        auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    ) as client:
        if not project_key:
            project_key = _detect_project_key(client)
        if not project_key:
            print("Missing project key. Set JIRA_PROJECT_KEY or pass --project-key.")
            return 1

        issue_type = _resolve_issue_type(client, project_key, args.issue_type)
        available_priorities = _fetch_priority_names(client)
        create_fields = _fetch_createmeta_fields(client, project_key, issue_type["id"])
        urgency_field = _extract_select_field(create_fields, "Urgency")
        impact_field = _extract_select_field(create_fields, "Impact")
        existing_seed_issues: dict[str, str] = {}
        if args.skip_existing or args.update_existing:
            existing_seed_issues = _fetch_existing_seed_issues(client, project_key)

        name_to_account: dict[str, str] = {}
        assignment_pool: list[str] = []
        if args.sync_users:
            name_to_account, assignment_pool = _sync_local_users_to_jira(
                client,
                project_key=project_key,
                local_users=local_users,
                products=_parse_user_products(args.user_products),
                allow_create=args.apply,
            )
        else:
            myself = _get_myself_account_id(client)
            if myself:
                assignment_pool = [myself]

        assignment_load: dict[str, int] = {account_id: 0 for account_id in assignment_pool}

        def select_assignee_account(ticket: Ticket) -> str | None:
            explicit_name = (ticket.assignee or "").strip()
            explicit_account = name_to_account.get(explicit_name)
            if explicit_account:
                assignment_load[explicit_account] = assignment_load.get(explicit_account, 0) + 1
                return explicit_account
            if args.auto_assign and assignment_pool:
                chosen = min(assignment_pool, key=lambda aid: (assignment_load.get(aid, 0), aid))
                assignment_load[chosen] = assignment_load.get(chosen, 0) + 1
                return chosen
            return None

        print(f"Project: {project_key}")
        print(f"Issue type: {issue_type['name']} ({issue_type['id']})")
        print(f"Tickets loaded: {len(tickets)}")
        print(f"Skip existing: {args.skip_existing}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print(f"User sync enabled: {args.sync_users}")
        print(f"Auto assign enabled: {args.auto_assign}")
        print(f"Update existing enabled: {args.update_existing}")
        if urgency_field:
            print(f"Urgency field: {urgency_field['field_id']}")
        else:
            print("Urgency field: not found for this issue type")
        if impact_field:
            print(f"Impact field: {impact_field['field_id']}")
        else:
            print("Impact field: not found for this issue type")

        created_count = 0
        updated_existing = 0
        skipped_existing = 0
        planned_count = 0
        comment_count = 0
        failures: list[tuple[str, str]] = []

        for idx, ticket in enumerate(tickets, start=1):
            ticket_seed_label = _seed_label(ticket.id)
            existing_issue_key = existing_seed_issues.get(ticket_seed_label)

            jira_priority_name = _resolve_priority_name(ticket.priority, available_priorities)
            urgency_impact_fields = _build_urgency_impact_fields(
                local_priority=ticket.priority,
                urgency_field=urgency_field,
                impact_field=impact_field,
            )
            assignee_account_id = select_assignee_account(ticket)
            if not args.apply:
                planned_count += 1
                urgency_preview = urgency_impact_fields.get(str((urgency_field or {}).get("field_id")), {})
                impact_preview = urgency_impact_fields.get(str((impact_field or {}).get("field_id")), {})
                target_action = "update existing" if (args.skip_existing and existing_issue_key and args.update_existing) else "create"
                print(
                    f"[DRY-RUN {idx}/{len(tickets)}] would {target_action} {ticket.id} "
                    f"(priority={ticket.priority.value}, urgency={urgency_preview.get('value')}, "
                    f"impact={impact_preview.get('value')}, assignee_account={assignee_account_id}, "
                    f"comments={len(ticket.comments or [])})"
                )
                continue

            try:
                if args.skip_existing and existing_issue_key:
                    if args.update_existing:
                        _update_issue(
                            client,
                            issue_key=existing_issue_key,
                            ticket=ticket,
                            jira_priority_name=jira_priority_name,
                            assignee_account_id=assignee_account_id,
                            extra_fields=urgency_impact_fields,
                        )
                        updated_existing += 1
                        print(
                            f"[{idx}/{len(tickets)}] updated {ticket.id} -> {existing_issue_key} "
                            f"(comments=0, assignee_account={assignee_account_id})"
                        )
                    else:
                        skipped_existing += 1
                    continue

                issue_key = _create_issue(
                    client,
                    project_key=project_key,
                    issue_type_id=issue_type["id"],
                    ticket=ticket,
                    jira_priority_name=jira_priority_name,
                    assignee_account_id=assignee_account_id,
                    extra_fields=urgency_impact_fields,
                )
                created_count += 1
                existing_seed_issues[ticket_seed_label] = issue_key
                added_comments = _add_comments(
                    client,
                    issue_key,
                    ticket,
                    max_comments=args.max_comments,
                    sleep_seconds=sleep_seconds,
                )
                comment_count += added_comments
                print(
                    f"[{idx}/{len(tickets)}] imported {ticket.id} -> {issue_key} "
                    f"(comments={added_comments}, assignee_account={assignee_account_id})"
                )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                failures.append((ticket.id, str(exc)))
                print(f"[{idx}/{len(tickets)}] FAILED {ticket.id}: {exc}")

    print("\nSummary:")
    print(f"- planned: {planned_count}")
    print(f"- created: {created_count}")
    print(f"- updated existing: {updated_existing}")
    print(f"- comments added: {comment_count}")
    print(f"- skipped existing: {skipped_existing}")
    print(f"- failed: {len(failures)}")
    if failures:
        for ticket_id, reason in failures[:10]:
            print(f"  - {ticket_id}: {reason}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
