"""Business logic for Jira -> DB reverse sync (webhook + reconcile)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.jira.client import JiraClient
from app.integrations.jira.mapper import JIRA_SOURCE, map_issue, map_issue_comment
from app.integrations.jira.schemas import JiraReconcileRequest, JiraReconcileResult, JiraWebhookResponse
from app.models.jira_sync_state import JiraSyncState
from app.models.ticket import Ticket, TicketComment

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_HEADER = "X-Jira-Webhook-Secret"
LEGACY_WEBHOOK_SIGNATURE_HEADER = "X-Signature"
SYNC_FIELDS = "summary,description,comment,priority,status,assignee,reporter,created,updated,labels,components,issuetype"
RECONCILE_SAFETY_WINDOW = dt.timedelta(minutes=2)


@dataclass
class SyncCounts:
    tickets_upserted: int = 0
    comments_upserted: int = 0
    comments_updated: int = 0
    skipped: int = 0


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_project_key(value: str | None) -> str:
    return (value or settings.JIRA_PROJECT_KEY or "").strip()


def _project_key_from_issue_key(issue_key: str) -> str:
    value = (issue_key or "").strip()
    if "-" not in value:
        return ""
    return value.split("-", 1)[0].strip()


def _detect_project_key(client: JiraClient) -> str:
    since_iso = (_utcnow() - dt.timedelta(days=3650)).strftime("%Y-%m-%d %H:%M")
    try:
        page = client.search_updated_issues(
            since_iso=since_iso,
            start_at=0,
            max_results=1,
            project_key=None,
        )
    except Exception:  # noqa: BLE001
        return ""
    issues = [item for item in list(page.get("issues") or []) if isinstance(item, dict)]
    if not issues:
        return ""
    issue_key = str(issues[0].get("key") or "").strip()
    return _project_key_from_issue_key(issue_key)


def _internal_ticket_id(seed: str) -> str:
    normalized = "".join(ch for ch in seed if ch.isalnum() or ch == "-").upper()
    candidate = f"JSM-{normalized}"[:20]
    if len(candidate) >= 8:
        return candidate
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"JSM-{digest}"


def _internal_comment_id() -> str:
    return f"jc{uuid4().hex[:18]}"


def _resolve_sync_state(db: Session, project_key: str) -> JiraSyncState:
    state = db.query(JiraSyncState).filter(JiraSyncState.project_key == project_key).first()
    if state:
        return state
    state = JiraSyncState(project_key=project_key, last_synced_at=None, last_error=None)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def _normalized_signature(signature_header: str | None) -> str:
    value = (signature_header or "").strip()
    if not value:
        return ""
    if value.lower().startswith("sha256="):
        return value.split("=", 1)[1].strip()
    return value


def validate_webhook_secret(
    secret_header: str | None,
    *,
    signature_header: str | None = None,
    raw_body: bytes | None = None,
) -> bool:
    configured = (settings.JIRA_WEBHOOK_SECRET or "").strip()
    if not configured:
        return True

    provided = (secret_header or "").strip()
    if provided and hmac.compare_digest(configured, provided):
        return True

    signature = _normalized_signature(signature_header)
    if signature and raw_body is not None:
        expected = hmac.new(configured.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return True

    return False


def _extract_issue_key(payload: dict[str, Any]) -> str:
    issue = payload.get("issue")
    if isinstance(issue, dict):
        key = str(issue.get("key") or "").strip()
        if key:
            return key
    return str(payload.get("issueKey") or "").strip()


def _build_reconcile_jql(project_key: str, since: dt.datetime) -> str:
    since_utc = since.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f'project = "{project_key}" AND updated >= "{since_utc}" ORDER BY updated ASC'


def _all_issue_comments(issue: dict[str, Any], jira_client: JiraClient) -> list[dict[str, Any]]:
    fields = issue.get("fields") or {}
    comment_field = fields.get("comment") or {}
    comments = [item for item in list(comment_field.get("comments") or []) if isinstance(item, dict)]
    total = int(comment_field.get("total") or len(comments))
    if total <= len(comments):
        return comments

    issue_key = str(issue.get("key") or "").strip()
    if not issue_key:
        return comments

    rows: list[dict[str, Any]] = []
    start_at = 0
    page_size = 100
    while True:
        page = jira_client.get_issue_comments(issue_key, start_at=start_at, max_results=page_size)
        chunk = [item for item in list(page.get("comments") or []) if isinstance(item, dict)]
        if not chunk:
            break
        rows.extend(chunk)
        start_at += len(chunk)
        if start_at >= int(page.get("total") or 0):
            break
    return rows or comments


def _find_ticket_for_issue(db: Session, *, jira_issue_id: str, jira_key: str) -> Ticket | None:
    if jira_issue_id:
        ticket = db.query(Ticket).filter(Ticket.jira_issue_id == jira_issue_id).first()
        if ticket:
            return ticket
    if jira_key:
        ticket = db.query(Ticket).filter(Ticket.jira_key == jira_key).first()
        if ticket:
            return ticket
        # Backward compatibility with historical external_id linkage.
        ticket = db.query(Ticket).filter(Ticket.external_id == jira_key).first()
        if ticket:
            return ticket
    return None


def _should_update_ticket(existing: Ticket, incoming_updated: dt.datetime | None) -> bool:
    if existing.jira_updated_at is None:
        return True
    if incoming_updated is None:
        return False
    return incoming_updated > existing.jira_updated_at


def _upsert_ticket(db: Session, issue: dict[str, Any]) -> tuple[Ticket, bool]:
    now = _utcnow()
    mapped = map_issue(issue)
    ticket = _find_ticket_for_issue(
        db,
        jira_issue_id=mapped.jira_issue_id,
        jira_key=mapped.jira_key,
    )
    if ticket is None:
        ticket = Ticket(
            id=_internal_ticket_id(mapped.jira_key or mapped.jira_issue_id),
            title=mapped.title,
            description=mapped.description,
            status=mapped.status,
            priority=mapped.priority,
            category=mapped.category,
            assignee=mapped.assignee,
            reporter=mapped.reporter,
            tags=mapped.tags,
            created_at=mapped.jira_created_at or now,
            updated_at=now,
            jira_key=mapped.jira_key,
            jira_issue_id=mapped.jira_issue_id,
            jira_created_at=mapped.jira_created_at,
            jira_updated_at=mapped.jira_updated_at,
            source=mapped.source,
            external_id=mapped.jira_key,
            external_source=mapped.source,
            external_updated_at=mapped.jira_updated_at,
            last_synced_at=now,
            raw_payload=mapped.raw_payload,
        )
        db.add(ticket)
        db.flush()
        return ticket, True

    if not _should_update_ticket(ticket, mapped.jira_updated_at):
        ticket.last_synced_at = now
        ticket.jira_key = ticket.jira_key or mapped.jira_key
        ticket.jira_issue_id = ticket.jira_issue_id or mapped.jira_issue_id
        ticket.source = JIRA_SOURCE
        ticket.external_id = ticket.external_id or mapped.jira_key
        ticket.external_source = ticket.external_source or JIRA_SOURCE
        db.add(ticket)
        db.flush()
        return ticket, False

    ticket.title = mapped.title
    ticket.description = mapped.description
    ticket.status = mapped.status
    ticket.priority = mapped.priority
    ticket.category = mapped.category
    ticket.assignee = mapped.assignee
    ticket.reporter = mapped.reporter
    ticket.tags = mapped.tags
    ticket.updated_at = now
    ticket.jira_key = mapped.jira_key
    ticket.jira_issue_id = mapped.jira_issue_id
    ticket.jira_created_at = mapped.jira_created_at
    ticket.jira_updated_at = mapped.jira_updated_at
    ticket.source = JIRA_SOURCE
    ticket.external_id = mapped.jira_key
    ticket.external_source = JIRA_SOURCE
    ticket.external_updated_at = mapped.jira_updated_at
    ticket.last_synced_at = now
    ticket.raw_payload = mapped.raw_payload
    db.add(ticket)
    db.flush()
    return ticket, True


def _should_update_comment(existing: TicketComment, incoming_updated: dt.datetime | None) -> bool:
    if existing.jira_updated_at is None:
        return True
    if incoming_updated is None:
        return False
    return incoming_updated > existing.jira_updated_at


def _upsert_comment(db: Session, *, ticket: Ticket, comment_payload: dict[str, Any]) -> str:
    now = _utcnow()
    mapped = map_issue_comment(comment_payload)
    existing = db.query(TicketComment).filter(TicketComment.jira_comment_id == mapped.jira_comment_id).first()
    if existing is None and mapped.jira_comment_id:
        # Backward compatibility with historical external_comment_id linkage.
        existing = (
            db.query(TicketComment)
            .filter(TicketComment.external_comment_id == mapped.jira_comment_id)
            .first()
        )

    if existing is None:
        created = TicketComment(
            id=_internal_comment_id(),
            ticket_id=ticket.id,
            author=mapped.author,
            content=mapped.content,
            created_at=mapped.jira_created_at or now,
            updated_at=now,
            jira_comment_id=mapped.jira_comment_id,
            jira_created_at=mapped.jira_created_at,
            jira_updated_at=mapped.jira_updated_at,
            external_comment_id=mapped.jira_comment_id,
            external_source=JIRA_SOURCE,
            external_updated_at=mapped.jira_updated_at,
            raw_payload=mapped.raw_payload,
        )
        db.add(created)
        db.flush()
        return "upserted"

    if not _should_update_comment(existing, mapped.jira_updated_at):
        return "skipped"

    existing.ticket_id = ticket.id
    existing.author = mapped.author
    existing.content = mapped.content
    existing.updated_at = now
    existing.jira_comment_id = mapped.jira_comment_id
    existing.jira_created_at = mapped.jira_created_at
    existing.jira_updated_at = mapped.jira_updated_at
    existing.external_comment_id = mapped.jira_comment_id
    existing.external_source = JIRA_SOURCE
    existing.external_updated_at = mapped.jira_updated_at
    existing.raw_payload = mapped.raw_payload
    db.add(existing)
    db.flush()
    return "updated"


def _upsert_issue_bundle(db: Session, issue: dict[str, Any], jira_client: JiraClient) -> SyncCounts:
    counts = SyncCounts()
    ticket, ticket_upserted = _upsert_ticket(db, issue)
    if ticket_upserted:
        counts.tickets_upserted += 1
    else:
        counts.skipped += 1

    for comment_payload in _all_issue_comments(issue, jira_client):
        try:
            state = _upsert_comment(db, ticket=ticket, comment_payload=comment_payload)
        except ValueError:
            counts.skipped += 1
            continue
        if state == "upserted":
            counts.comments_upserted += 1
        elif state == "updated":
            counts.comments_updated += 1
        else:
            counts.skipped += 1
    return counts


def _merge_counts(total: SyncCounts, delta: SyncCounts) -> None:
    total.tickets_upserted += delta.tickets_upserted
    total.comments_upserted += delta.comments_upserted
    total.comments_updated += delta.comments_updated
    total.skipped += delta.skipped


def sync_issue_by_key(db: Session, issue_key: str, *, jira_client: JiraClient | None = None) -> SyncCounts:
    key = (issue_key or "").strip()
    if not key:
        raise ValueError("missing_issue_key")

    client = jira_client or JiraClient()
    issue = client.get_issue(key, fields=SYNC_FIELDS)
    if not isinstance(issue, dict) or not issue:
        raise ValueError("issue_fetch_failed")

    counts = _upsert_issue_bundle(db, issue, client)
    db.commit()
    return counts


def sync_issue_from_webhook_payload(db: Session, payload: dict[str, Any]) -> JiraWebhookResponse:
    issue_key = _extract_issue_key(payload)
    if not issue_key:
        raise ValueError("missing_issue_key")

    counts = sync_issue_by_key(db, issue_key)
    return JiraWebhookResponse(
        issue_key=issue_key,
        tickets_upserted=counts.tickets_upserted,
        comments_upserted=counts.comments_upserted,
        comments_updated=counts.comments_updated,
        skipped=counts.skipped,
    )


def reconcile(db: Session, payload: JiraReconcileRequest) -> JiraReconcileResult:
    client = JiraClient()
    project_key = _normalize_project_key(payload.project_key) or _detect_project_key(client)
    if not project_key:
        raise ValueError("missing_project_key")
    state = _resolve_sync_state(db, project_key)

    now = _utcnow()
    lookback_start = now - dt.timedelta(days=max(1, payload.lookback_days))
    baseline = state.last_synced_at or lookback_start
    since = baseline - RECONCILE_SAFETY_WINDOW
    jql = _build_reconcile_jql(project_key, since)

    start_at = 0
    pages = 0
    issues_seen = 0
    errors: list[str] = []
    counts = SyncCounts()
    max_processed_updated = state.last_synced_at

    while True:
        page = client.search_jql(
            jql=jql,
            start_at=start_at,
            max_results=settings.JIRA_SYNC_PAGE_SIZE,
            fields=SYNC_FIELDS,
        )
        issues = [item for item in list(page.get("issues") or []) if isinstance(item, dict)]
        if not issues:
            break

        pages += 1
        for issue in issues:
            issue_key = str(issue.get("key") or "").strip()
            if not issue_key:
                counts.skipped += 1
                continue
            issues_seen += 1
            try:
                full_issue = client.get_issue(issue_key, fields=SYNC_FIELDS)
                delta = _upsert_issue_bundle(db, full_issue, client)
                _merge_counts(counts, delta)
                mapped = map_issue(full_issue)
                if mapped.jira_updated_at and (
                    max_processed_updated is None or mapped.jira_updated_at > max_processed_updated
                ):
                    max_processed_updated = mapped.jira_updated_at
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                message = f"{issue_key}: {exc}"
                errors.append(message)
                logger.exception("Jira reconcile failed for issue %s", issue_key)

        start_at += len(issues)
        if start_at >= int(page.get("total") or 0):
            break

    state.last_synced_at = max_processed_updated or state.last_synced_at
    state.last_error = "; ".join(errors[:5]) if errors else None
    state.updated_at = _utcnow()
    db.add(state)
    db.commit()

    return JiraReconcileResult(
        project_key=project_key,
        since=since,
        last_synced_at=state.last_synced_at,
        issues_seen=issues_seen,
        pages=pages,
        tickets_upserted=counts.tickets_upserted,
        comments_upserted=counts.comments_upserted,
        comments_updated=counts.comments_updated,
        skipped=counts.skipped,
        errors=errors,
    )
