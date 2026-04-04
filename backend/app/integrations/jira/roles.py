"""Helpers to align local user roles with Jira Service Management project roles."""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.jira.client import JiraClient
from app.models.enums import UserRole
from app.models.user import User

logger = logging.getLogger(__name__)

MANAGED_PROJECT_ROLE_NAMES = (
    "Administrators",
    "Service Desk Team",
    "Service Desk Customers",
)
PROJECT_ROLE_NAMES_BY_LOCAL_ROLE: dict[UserRole, tuple[str, ...]] = {
    UserRole.admin: ("Administrators", "Service Desk Team"),
    UserRole.agent: ("Service Desk Team",),
    UserRole.user: ("Service Desk Customers",),
    UserRole.viewer: ("Service Desk Customers",),
}


def _identity(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _candidate_queries(*values: str | None) -> list[str]:
    candidates: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        candidates.append(raw)
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


def _find_local_user(db: Session, identity_value: str | None) -> User | None:
    raw = str(identity_value or "").strip()
    if not raw:
        return None
    if "@" in raw:
        user = db.query(User).filter(User.email.ilike(raw)).first()
        if user:
            return user
    return db.query(User).filter(User.name.ilike(raw)).first()


def _find_account_id(client: JiraClient, user: User) -> str | None:
    target_identities = {
        _identity(str(user.email or "").strip()),
        _identity(str(user.name or "").strip()),
    }
    for query in _candidate_queries(user.email, user.name):
        try:
            rows = client.search_users(query, max_results=20)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira user search failed for %s (%s): %s", user.name, query, exc)
            continue
        for row in rows:
            account_id = str(row.get("accountId") or row.get("id") or "").strip()
            if not account_id or not bool(row.get("active", True)):
                continue
            row_identities = {
                _identity(str(row.get("displayName") or "").strip()),
                _identity(str(row.get("emailAddress") or "").strip()),
                _identity(account_id),
            }
            if target_identities.intersection(row_identities):
                return account_id
        if rows:
            fallback = str((rows[0] or {}).get("accountId") or (rows[0] or {}).get("id") or "").strip()
            if fallback:
                return fallback
    return None


def _ensure_account_id(client: JiraClient, user: User) -> str | None:
    account_id = _find_account_id(client, user)
    if account_id:
        return account_id

    email = str(user.email or "").strip()
    if not email:
        return None

    try:
        created = client.create_customer(
            display_name=str(user.name or "").strip() or email,
            email=email,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira customer create failed for %s: %s", email, exc)
        return None

    created_account_id = str(created.get("accountId") or created.get("id") or "").strip()
    if created_account_id:
        return created_account_id
    return _find_account_id(client, user)


def _role_id_from_url(url: str | None) -> str | None:
    value = str(url or "").rstrip("/")
    if not value:
        return None
    return value.rsplit("/", 1)[-1].strip() or None


def _account_ids_from_role_payload(payload: dict) -> set[str]:
    account_ids: set[str] = set()
    for actor in list(payload.get("actors") or []):
        if not isinstance(actor, dict):
            continue
        actor_user = actor.get("actorUser") or {}
        account_id = str(actor_user.get("accountId") or "").strip()
        if account_id:
            account_ids.add(account_id)
    return account_ids


def sync_jira_project_roles_for_user(
    user: User,
    *,
    client: JiraClient | None = None,
    project_key: str | None = None,
) -> str | None:
    if not settings.jira_ready:
        return None

    jira_client = client or JiraClient()
    resolved_project_key = str(project_key or settings.JIRA_PROJECT_KEY or "").strip()
    account_id = _ensure_account_id(jira_client, user)
    if not account_id or not resolved_project_key:
        return account_id

    try:
        role_urls = jira_client.get_project_roles(resolved_project_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira project role fetch failed for %s: %s", resolved_project_key, exc)
        return account_id

    desired_roles = set(PROJECT_ROLE_NAMES_BY_LOCAL_ROLE.get(user.role, ("Service Desk Customers",)))
    for role_name in MANAGED_PROJECT_ROLE_NAMES:
        role_url = role_urls.get(role_name)
        role_id = _role_id_from_url(role_url)
        if not role_id:
            continue
        try:
            payload = jira_client.get_project_role(resolved_project_key, role_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Jira project role detail fetch failed for %s/%s: %s", resolved_project_key, role_name, exc)
            continue

        current_ids = _account_ids_from_role_payload(payload)
        if role_name in desired_roles and account_id not in current_ids:
            jira_client.add_project_role_users(resolved_project_key, role_id, [account_id])
        elif role_name not in desired_roles and account_id in current_ids:
            jira_client.remove_project_role_users(resolved_project_key, role_id, [account_id])

    return account_id


def sync_jira_project_roles_for_identity(
    identity_value: str | None,
    *,
    client: JiraClient | None = None,
    project_key: str | None = None,
) -> str | None:
    raw = str(identity_value or "").strip()
    if not raw:
        return None
    with SessionLocal() as db:
        user = _find_local_user(db, raw)
        if not user:
            return None
        return sync_jira_project_roles_for_user(user, client=client, project_key=project_key)


def sync_jira_project_roles_for_all_users(
    db: Session,
    *,
    client: JiraClient | None = None,
    project_key: str | None = None,
) -> dict[str, str | None]:
    jira_client = client or JiraClient()
    results: dict[str, str | None] = {}
    users = db.query(User).order_by(User.name.asc()).all()
    for user in users:
        results[str(user.email)] = sync_jira_project_roles_for_user(
            user,
            client=jira_client,
            project_key=project_key,
        )
    return results
