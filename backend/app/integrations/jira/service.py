"""Business logic for Jira -> DB reverse sync (webhook + reconcile)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.jira.client import JiraClient
from app.integrations.jira.mapper import JIRA_SOURCE, map_issue, map_issue_comment
from app.integrations.jira.schemas import JiraReconcileRequest, JiraReconcileResult, JiraWebhookResponse
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.models.jira_sync_state import JiraSyncState
from app.models.ticket import Ticket, TicketComment
from app.models.user import User
from app.services.ai import classify_ticket
from app.services.ai.llm import ollama_generate

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_HEADER = "X-Jira-Webhook-Secret"
LEGACY_WEBHOOK_SIGNATURE_HEADER = "X-Signature"
SYNC_FIELDS = "summary,description,comment,priority,status,assignee,reporter,created,updated,labels,components,issuetype"
RECONCILE_SAFETY_WINDOW = dt.timedelta(minutes=2)
LOCAL_TICKET_SUMMARY_RE = re.compile(r"^\[(TW-\d+)\]\s*", re.IGNORECASE)
LOCAL_TICKET_LABEL_PREFIXES = ("twseed_tw_", "local_tw_")
DONE_STATUSES = {TicketStatus.resolved, TicketStatus.closed}
KNOWN_JIRA_ISSUE_TYPES = {"incident", "service request", "task", "bug", "problem"}
KNOWN_JIRA_PRIORITIES = {"highest", "critical", "high", "medium", "low", "lowest"}


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


def _extract_local_ticket_id(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    summary = str(fields.get("summary") or "").strip()
    match = LOCAL_TICKET_SUMMARY_RE.match(summary)
    if match:
        return match.group(1).upper()

    labels = [str(label).strip().lower() for label in list(fields.get("labels") or []) if str(label).strip()]
    for label in labels:
        for prefix in LOCAL_TICKET_LABEL_PREFIXES:
            if not label.startswith(prefix):
                continue
            suffix = label[len(prefix) :].strip().replace("_", "-").upper()
            if re.fullmatch(r"\d+", suffix):
                suffix = f"TW-{suffix}"
            if re.fullmatch(r"TW-\d+", suffix):
                return suffix
    return ""


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


def _is_done_status(status: TicketStatus) -> bool:
    return status in DONE_STATUSES


def _extract_first_agent_comment_at(ticket: Ticket, comments: list[dict[str, Any]]) -> dt.datetime | None:
    reporter = (ticket.reporter or "").strip().casefold()
    first_seen: dt.datetime | None = None
    for payload in comments:
        try:
            mapped = map_issue_comment(payload)
        except Exception:  # noqa: BLE001
            continue
        author = (mapped.author or "").strip().casefold()
        # Jira payloads do not carry local role metadata; use reporter mismatch as a practical proxy.
        if reporter and author == reporter:
            continue
        ts = mapped.jira_created_at or mapped.jira_updated_at
        if ts is None:
            continue
        if first_seen is None or ts < first_seen:
            first_seen = ts
    return first_seen


def _apply_ticket_lifecycle_from_issue(ticket: Ticket, *, now: dt.datetime) -> None:
    if ticket.first_action_at is None and ticket.status != TicketStatus.open:
        ticket.first_action_at = ticket.jira_updated_at or now

    if _is_done_status(ticket.status):
        ticket.resolved_at = ticket.resolved_at or ticket.jira_updated_at or now
    elif ticket.resolved_at is not None:
        ticket.resolved_at = None


def _issue_type_name(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    return str(((fields.get("issuetype") or {}).get("name") or "")).strip().lower()


def _priority_name(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    return str(((fields.get("priority") or {}).get("name") or "")).strip().lower()


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


def _issue_description_missing(issue: dict[str, Any]) -> bool:
    fields = issue.get("fields") or {}
    description = fields.get("description")
    return not bool(_normalize_text(description))


def _resolve_assignee_specialization(db: Session, assignee_name: str) -> str:
    target = str(assignee_name or "").strip()
    if not target or target.lower() == "unassigned":
        return "general support"
    if not hasattr(db, "query"):
        return "general support"
    try:
        user = db.query(User).filter(User.name.ilike(target)).first()
    except Exception:  # noqa: BLE001
        return "general support"
    if not user:
        return "general support"
    specializations = [str(item).strip() for item in list(user.specializations or []) if str(item).strip()]
    if not specializations:
        return "general support"
    return ", ".join(specializations[:3])


def _enforce_generated_description_policy(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        cleaned = "Limited ticket details were provided. Initial triage should confirm scope, impact, and probable causes."
    words = cleaned.split()
    if len(words) > 120:
        cleaned = " ".join(words[:120]).rstrip(".,;: ")
    suffix = "This description was generated based on limited information."
    if not cleaned.endswith(suffix):
        cleaned = f"{cleaned.rstrip('. ')}. {suffix}"
    return cleaned


def _generate_missing_description(
    *,
    ticket_title: str,
    severity: str,
    assignee_specialization: str,
) -> str:
    prompt = (
        "You are an IT service management assistant.\n\n"
        "A Jira ticket has no description.\n\n"
        "Available information:\n"
        f'- Title: "{ticket_title}"\n'
        f'- Severity: "{severity}"\n'
        f'- Assignee specialization: "{assignee_specialization}"\n\n'
        "Generate a realistic and concise technical description\n"
        "that could plausibly explain this issue.\n\n"
        "Rules:\n"
        "- Do NOT invent specific IPs, systems, or user names.\n"
        "- Do NOT claim facts that are not supported.\n"
        "- Keep it generic but operationally useful.\n"
        "- Max 120 words.\n"
        "- Write in professional ITSM language.\n"
        '- End with: "This description was generated based on limited information."\n\n'
        "Return only the description."
    )
    try:
        generated = ollama_generate(prompt, json_mode=False)
    except Exception as exc:  # noqa: BLE001
        logger.info("Missing-description generation failed, using fallback: %s", exc)
        generated = (
            f"Ticket reported with severity {severity}. The issue appears related to {ticket_title}. "
            "Initial handling should validate impact scope, identify likely cause domains, and document mitigation steps."
        )
    return _enforce_generated_description_policy(generated)


def _category_was_defaulted(issue: dict[str, Any], mapped_category: TicketCategory) -> bool:
    issue_type = _issue_type_name(issue)
    if not issue_type:
        return True
    if issue_type in KNOWN_JIRA_ISSUE_TYPES:
        return False
    return True


def _priority_was_defaulted(issue: dict[str, Any], mapped_priority: TicketPriority) -> bool:
    value = _priority_name(issue)
    if not value:
        return True
    if value in KNOWN_JIRA_PRIORITIES:
        return False
    return mapped_priority == TicketPriority.medium


def _classify_inbound_ticket(title: str, description: str) -> tuple[TicketPriority | None, TicketCategory | None]:
    try:
        priority, category, _recommendations = classify_ticket(title, description)
        return priority, category
    except Exception:  # noqa: BLE001
        return None, None


def _find_ticket_for_issue(
    db: Session,
    *,
    jira_issue_id: str,
    jira_key: str,
    local_ticket_id: str = "",
) -> Ticket | None:
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
    if local_ticket_id:
        ticket = db.get(Ticket, local_ticket_id)
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
    specialization = _resolve_assignee_specialization(db, mapped.assignee)
    if _issue_description_missing(issue):
        mapped = mapped.__class__(
            jira_key=mapped.jira_key,
            jira_issue_id=mapped.jira_issue_id,
            source=mapped.source,
            title=mapped.title,
            description=_generate_missing_description(
                ticket_title=mapped.title,
                severity=mapped.priority.value,
                assignee_specialization=specialization,
            ),
            status=mapped.status,
            priority=mapped.priority,
            category=mapped.category,
            assignee=mapped.assignee,
            reporter=mapped.reporter,
            tags=mapped.tags,
            jira_created_at=mapped.jira_created_at,
            jira_updated_at=mapped.jira_updated_at,
            raw_payload=mapped.raw_payload,
        )
    local_ticket_id = _extract_local_ticket_id(issue)
    ticket = _find_ticket_for_issue(
        db,
        jira_issue_id=mapped.jira_issue_id,
        jira_key=mapped.jira_key,
        local_ticket_id=local_ticket_id,
    )

    ai_priority: TicketPriority | None = None
    ai_category: TicketCategory | None = None
    resolved_priority = mapped.priority
    resolved_category = mapped.category
    ai_applied = False

    def resolve_classification() -> None:
        nonlocal ai_priority, ai_category, resolved_priority, resolved_category, ai_applied
        ai_priority, ai_category = _classify_inbound_ticket(mapped.title, mapped.description)
        if ai_category is not None and _category_was_defaulted(issue, mapped.category):
            resolved_category = ai_category
        if ai_priority is not None and _priority_was_defaulted(issue, mapped.priority):
            resolved_priority = ai_priority
        ai_applied = ai_priority is not None or ai_category is not None

    if ticket is None:
        resolve_classification()
        ticket = Ticket(
            id=_internal_ticket_id(mapped.jira_key or mapped.jira_issue_id),
            title=mapped.title,
            description=mapped.description,
            status=mapped.status,
            priority=resolved_priority,
            category=resolved_category,
            assignee=mapped.assignee,
            reporter=mapped.reporter,
            tags=mapped.tags,
            created_at=mapped.jira_created_at or now,
            updated_at=now,
            auto_priority_applied=ai_applied,
            priority_model_version="smart-v1" if ai_applied else "jira-native",
            predicted_priority=ai_priority,
            predicted_category=ai_category,
            assignment_change_count=0,
            first_action_at=None,
            resolved_at=None,
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
        _apply_ticket_lifecycle_from_issue(ticket, now=now)
        db.add(ticket)
        db.flush()
        return ticket, True

    if not _should_update_ticket(ticket, mapped.jira_updated_at):
        ticket.last_synced_at = now
        ticket.jira_key = ticket.jira_key or mapped.jira_key
        ticket.jira_issue_id = ticket.jira_issue_id or mapped.jira_issue_id
        ticket.source = ticket.source or JIRA_SOURCE
        ticket.external_id = ticket.external_id or mapped.jira_key
        ticket.external_source = ticket.external_source or JIRA_SOURCE
        db.add(ticket)
        db.flush()
        return ticket, False

    resolve_classification()
    previous_assignee = ticket.assignee
    ticket.title = mapped.title
    ticket.description = mapped.description
    ticket.status = mapped.status
    ticket.priority = resolved_priority
    ticket.category = resolved_category
    ticket.assignee = mapped.assignee
    ticket.reporter = mapped.reporter
    ticket.tags = mapped.tags
    ticket.predicted_priority = ai_priority
    ticket.predicted_category = ai_category
    ticket.auto_priority_applied = ai_applied
    ticket.priority_model_version = "smart-v1" if ai_applied else ticket.priority_model_version or "jira-native"
    ticket.updated_at = now
    ticket.jira_key = mapped.jira_key
    ticket.jira_issue_id = mapped.jira_issue_id
    ticket.jira_created_at = mapped.jira_created_at
    ticket.jira_updated_at = mapped.jira_updated_at
    ticket.source = ticket.source or JIRA_SOURCE
    ticket.external_id = mapped.jira_key
    ticket.external_source = JIRA_SOURCE
    ticket.external_updated_at = mapped.jira_updated_at
    ticket.last_synced_at = now
    ticket.raw_payload = mapped.raw_payload

    if previous_assignee and mapped.assignee and previous_assignee != mapped.assignee:
        ticket.assignment_change_count = int(ticket.assignment_change_count or 0) + 1

    _apply_ticket_lifecycle_from_issue(ticket, now=now)
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
    from app.services.problems import link_ticket_to_problem
    from app.integrations.jira.sla_sync import sync_ticket_sla
    from app.services.sla.auto_escalation import apply_escalation

    counts = SyncCounts()
    ticket, ticket_upserted = _upsert_ticket(db, issue)
    if ticket_upserted:
        counts.tickets_upserted += 1
    else:
        counts.skipped += 1

    try:
        if ticket.jira_key:
            sync_ticket_sla(db, ticket, ticket.jira_key, jira_client=jira_client)
            apply_escalation(db, ticket, actor="jira_reverse_sync")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira SLA sync/escalation skipped for %s: %s", ticket.id, exc)

    all_comments = _all_issue_comments(issue, jira_client)
    for comment_payload in all_comments:
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

    first_agent_comment = _extract_first_agent_comment_at(ticket, all_comments)
    if first_agent_comment is not None:
        if ticket.first_action_at is None or first_agent_comment < ticket.first_action_at:
            ticket.first_action_at = first_agent_comment
            db.add(ticket)

    _apply_ticket_lifecycle_from_issue(ticket, now=_utcnow())
    db.add(ticket)
    db.flush()
    link_ticket_to_problem(db, ticket)
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
