"""Business logic for Jira reverse sync (webhook upsert + reconcile)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.jira.client import JiraClient
from app.integrations.jira.mapper import JIRA_SOURCE, NormalizedComment, NormalizedTicket, map_issue, map_issue_comment
from app.integrations.jira.schemas import JiraReconcileRequest, JiraReconcileResult, JiraUpsertResult
from app.models.jira_sync_state import JiraSyncState
from app.models.ticket import Ticket, TicketComment

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Signature"
SYNC_ORIGIN_HEADER = "X-Sync-Origin"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _internal_ticket_id_from_external(external_id: str) -> str:
    normalized = "".join(ch for ch in external_id if ch.isalnum() or ch == "-").upper()
    candidate = f"JSM-{normalized}"[:20]
    if len(candidate) >= 8:
        return candidate
    digest = hashlib.sha1(external_id.encode("utf-8")).hexdigest()[:8]
    return f"JSM-{digest}"


def _internal_comment_id() -> str:
    return f"jc{uuid4().hex[:18]}"


def _parse_issue_from_payload(payload: dict[str, Any], jira_client: JiraClient) -> dict[str, Any]:
    issue = payload.get("issue")
    if isinstance(issue, dict) and issue.get("key"):
        return issue

    issue_key = str(payload.get("issueKey") or payload.get("jira_key") or "").strip()
    if not issue_key:
        raise ValueError("missing_issue_key")

    fields = payload.get("fields")
    comments = payload.get("comments")
    if isinstance(fields, dict):
        issue_payload = {"key": issue_key, "fields": dict(fields)}
        if isinstance(comments, list):
            issue_payload["fields"]["comment"] = {"comments": comments}
        return issue_payload

    return jira_client.get_issue(issue_key, expand="changelog")


def _fetch_all_comments(jira_client: JiraClient, issue_key: str) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    start_at = 0
    page_size = 100
    while True:
        page = jira_client.get_issue_comments(issue_key, start_at=start_at, max_results=page_size)
        rows = list(page.get("comments") or [])
        if not rows:
            break
        comments.extend([row for row in rows if isinstance(row, dict)])
        start_at += len(rows)
        if start_at >= int(page.get("total") or 0):
            break
    return comments


def _upsert_ticket(db: Session, mapped: NormalizedTicket) -> tuple[Ticket, bool, bool]:
    now = _utcnow()
    existing = (
        db.query(Ticket)
        .filter(Ticket.external_source == mapped.external_source, Ticket.external_id == mapped.external_id)
        .first()
    )
    created = existing is None
    should_update = (
        created
        or existing.external_updated_at is None
        or (mapped.external_updated_at and mapped.external_updated_at > existing.external_updated_at)
    )

    insert_values: dict[str, Any] = {
        "id": _internal_ticket_id_from_external(mapped.external_id),
        "title": mapped.title,
        "description": mapped.description,
        "status": mapped.status,
        "priority": mapped.priority,
        "category": mapped.category,
        "assignee": mapped.assignee,
        "reporter": mapped.reporter,
        "tags": mapped.tags,
        "created_at": mapped.created_at or now,
        "updated_at": now,
        "external_id": mapped.external_id,
        "external_source": mapped.external_source,
        "external_updated_at": mapped.external_updated_at,
        "last_synced_at": now,
        "raw_payload": mapped.raw_payload,
    }
    if existing:
        insert_values["id"] = existing.id

    stmt = insert(Ticket).values(**insert_values)
    update_set = {
        "title": stmt.excluded.title,
        "description": stmt.excluded.description,
        "status": stmt.excluded.status,
        "priority": stmt.excluded.priority,
        "category": stmt.excluded.category,
        "assignee": stmt.excluded.assignee,
        "reporter": stmt.excluded.reporter,
        "tags": stmt.excluded.tags,
        "updated_at": stmt.excluded.updated_at,
        "external_updated_at": stmt.excluded.external_updated_at,
        "last_synced_at": stmt.excluded.last_synced_at,
        "raw_payload": stmt.excluded.raw_payload,
    }

    stmt = stmt.on_conflict_do_update(
        constraint="uq_tickets_external_source_external_id",
        set_=update_set,
        where=or_(Ticket.external_updated_at.is_(None), stmt.excluded.external_updated_at > Ticket.external_updated_at),
    )
    db.execute(stmt)

    if existing and not should_update:
        existing.last_synced_at = now
        db.add(existing)

    db.commit()
    ticket = (
        db.query(Ticket)
        .filter(Ticket.external_source == mapped.external_source, Ticket.external_id == mapped.external_id)
        .first()
    )
    if not ticket:
        raise RuntimeError(f"ticket_upsert_failed:{mapped.external_id}")
    return ticket, created, bool(should_update and not created)


def _upsert_comment(db: Session, ticket: Ticket, mapped: NormalizedComment) -> None:
    now = _utcnow()
    existing = (
        db.query(TicketComment)
        .filter(
            TicketComment.ticket_id == ticket.id,
            TicketComment.external_comment_id == mapped.external_comment_id,
        )
        .first()
    )
    should_update = (
        existing is None
        or existing.external_updated_at is None
        or (mapped.external_updated_at and mapped.external_updated_at > existing.external_updated_at)
    )

    insert_values = {
        "id": existing.id if existing else _internal_comment_id(),
        "ticket_id": ticket.id,
        "author": mapped.author,
        "content": mapped.content,
        "created_at": mapped.created_at or now,
        "updated_at": now,
        "external_comment_id": mapped.external_comment_id,
        "external_source": mapped.external_source,
        "external_updated_at": mapped.external_updated_at,
        "raw_payload": mapped.raw_payload,
    }
    stmt = insert(TicketComment).values(**insert_values)
    update_set = {
        "author": stmt.excluded.author,
        "content": stmt.excluded.content,
        "updated_at": stmt.excluded.updated_at,
        "external_updated_at": stmt.excluded.external_updated_at,
        "raw_payload": stmt.excluded.raw_payload,
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ticket_comments_ticket_external_comment",
        set_=update_set,
        where=or_(
            TicketComment.external_updated_at.is_(None),
            stmt.excluded.external_updated_at > TicketComment.external_updated_at,
        ),
    )
    db.execute(stmt)

    if existing and not should_update:
        existing.updated_at = now
        db.add(existing)


def validate_signature(*, raw_body: bytes, signature_header: str | None) -> bool:
    secret = settings.JIRA_WEBHOOK_SECRET.strip()
    if not secret:
        return True
    if not signature_header:
        return False
    received = signature_header.strip()
    if "=" in received:
        _, received = received.split("=", 1)
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, received.strip())


def is_loopback_sync(*, payload: dict[str, Any], sync_origin: str | None) -> bool:
    header_origin = (sync_origin or "").strip().lower()
    body_origin = str(payload.get("origin") or payload.get("sync_origin") or "").strip().lower()
    return header_origin in {"backend", "db-sync"} or body_origin in {"backend", "db-sync"}


def upsert_from_payload(db: Session, payload: dict[str, Any]) -> JiraUpsertResult:
    jira_client = JiraClient()
    issue = _parse_issue_from_payload(payload, jira_client)
    mapped_ticket = map_issue(issue)
    ticket, created, updated = _upsert_ticket(db, mapped_ticket)

    comments_raw = []
    issue_comments = (((issue.get("fields") or {}).get("comment") or {}).get("comments") or [])
    if issue_comments:
        comments_raw = [row for row in issue_comments if isinstance(row, dict)]
    else:
        comments_raw = _fetch_all_comments(jira_client, mapped_ticket.external_id)

    for comment_payload in comments_raw:
        try:
            mapped_comment = map_issue_comment(comment_payload)
        except ValueError:
            continue
        _upsert_comment(db, ticket, mapped_comment)

    db.commit()
    logger.info(
        "Jira upsert completed: key=%s created=%s updated=%s comments=%d",
        mapped_ticket.external_id,
        created,
        updated,
        len(comments_raw),
    )
    return JiraUpsertResult(
        jira_key=mapped_ticket.external_id,
        created=created,
        updated=updated,
    )


def _resolve_sync_state(db: Session, project_key: str) -> JiraSyncState:
    state = db.query(JiraSyncState).filter(JiraSyncState.project_key == project_key).first()
    if state:
        return state
    state = JiraSyncState(project_key=project_key, last_synced_at=None, last_cursor=None)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def reconcile(db: Session, payload: JiraReconcileRequest) -> JiraReconcileResult:
    jira_client = JiraClient()
    project_key = (payload.project_key or settings.JIRA_PROJECT_KEY or "default").strip() or "default"
    state = _resolve_sync_state(db, project_key)

    since_dt = payload.since or state.last_synced_at or (_utcnow() - dt.timedelta(days=1))
    since_iso = since_dt.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    start_at = 0
    fetched = 0
    created = 0
    updated = 0
    unchanged = 0
    errors: list[str] = []
    latest_seen = since_dt
    latest_key = state.last_cursor

    while True:
        page = jira_client.search_updated_issues(
            since_iso=since_iso,
            start_at=start_at,
            max_results=settings.JIRA_SYNC_PAGE_SIZE,
            project_key=project_key if project_key != "default" else None,
        )
        issues = list(page.get("issues") or [])
        if not issues:
            break
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            fetched += 1
            try:
                result = upsert_from_payload(db, {"issue": issue})
                if result.created:
                    created += 1
                elif result.updated:
                    updated += 1
                else:
                    unchanged += 1
                mapped_updated_at = map_issue(issue).external_updated_at
                if mapped_updated_at and mapped_updated_at > latest_seen:
                    latest_seen = mapped_updated_at
                latest_key = str(issue.get("key") or latest_key or "")
            except Exception as exc:
                key = str(issue.get("key") or "unknown")
                errors.append(f"{key}: {exc}")
                logger.exception("Jira reconcile failed for issue: %s", key)
        start_at += len(issues)
        if start_at >= int(page.get("total") or 0):
            break

    state.last_synced_at = latest_seen
    state.last_cursor = latest_key
    state.updated_at = _utcnow()
    db.add(state)
    db.commit()

    return JiraReconcileResult(
        project_key=project_key,
        since=since_dt,
        fetched=fetched,
        created=created,
        updated=updated,
        unchanged=unchanged,
        errors=errors,
    )
