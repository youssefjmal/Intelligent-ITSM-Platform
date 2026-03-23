"""Sync the existing local mock dataset to Jira/JSM without reconcile or KB refresh.

This script is intentionally narrow:
- uses the current local DB dataset as source of truth
- backs up current Jira issue summaries
- deletes current Jira project issues
- pushes local tickets and comments to Jira/JSM
- skips reconcile, SLA sync, and KB refresh
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BASE_DIR.parent
sys.path.append(str(BASE_DIR))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.integrations.jira.client import JiraClient  # noqa: E402
from app.integrations.jira.mapper import _parse_datetime as parse_jira_datetime  # noqa: E402
from app.integrations.jira.outbound import (  # noqa: E402
    _adf_from_text,
    _format_comment_text_for_jira,
    _sync_issue_status,
    create_jira_issue_for_ticket,
    sync_jira_issue_for_ticket,
)
from app.models.problem import Problem  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402


def json_default(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def backup_path() -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = REPO_ROOT / ".ops_backups"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"jira_sync_backup_{stamp}.json"


def fetch_project_issue_summaries(client: JiraClient, project_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_at = 0
    page_size = 100
    while True:
        page = client.search_jql(
            jql=f'project = "{project_key}" ORDER BY key ASC',
            start_at=start_at,
            max_results=page_size,
            fields="summary,status,assignee,reporter,duedate,comment",
        )
        issues = [item for item in list(page.get("issues") or []) if isinstance(item, dict)]
        if not issues:
            break
        rows.extend(issues)
        start_at += len(issues)
        if len(issues) < page_size:
            break
    return rows


def write_backup(client: JiraClient, project_key: str) -> Path:
    path = backup_path()
    db = SessionLocal()
    try:
        payload = {
            "captured_at": dt.datetime.now(dt.timezone.utc),
            "project_key": project_key,
            "jira_base_url": settings.JIRA_BASE_URL,
            "jira_issues": fetch_project_issue_summaries(client, project_key),
            "local_ticket_count": db.query(Ticket).count(),
            "local_comment_count": db.query(TicketComment).count(),
            "local_problem_count": db.query(Problem).count(),
        }
    finally:
        db.close()
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, default=json_default), encoding="utf-8")
    return path


def purge_jira_project(client: JiraClient, project_key: str) -> list[str]:
    issues = fetch_project_issue_summaries(client, project_key)
    deleted: list[str] = []
    for issue in reversed(issues):
        issue_key = str(issue.get("key") or "").strip()
        if not issue_key:
            continue
        client._request_empty("DELETE", f"/rest/api/3/issue/{issue_key}")  # noqa: SLF001
        deleted.append(issue_key)
    return deleted


def reset_local_jira_links() -> None:
    db = SessionLocal()
    try:
        for ticket in db.query(Ticket).all():
            ticket.jira_key = None
            ticket.jira_issue_id = None
            ticket.jira_created_at = None
            ticket.jira_updated_at = None
            ticket.external_id = None
            ticket.external_source = None
            ticket.external_updated_at = None
            ticket.last_synced_at = None
            db.add(ticket)

        for comment in db.query(TicketComment).all():
            comment.jira_comment_id = None
            comment.jira_created_at = None
            comment.jira_updated_at = None
            comment.external_comment_id = None
            comment.external_source = None
            comment.external_updated_at = None
            db.add(comment)
        db.commit()
    finally:
        db.close()


def converge_issue_status(client: JiraClient, ticket: Ticket) -> None:
    if not ticket.jira_key or ticket.status.value == "open":
        return
    for _ in range(5):
        issue = client.get_issue(ticket.jira_key, fields="status")
        status_name = str(((issue.get("fields") or {}).get("status") or {}).get("name") or "").strip().lower()
        if ticket.status.value == "resolved" and status_name in {"resolved", "done"}:
            return
        if ticket.status.value == "closed" and status_name == "closed":
            return
        if not _sync_issue_status(client, ticket):
            return


def push_comments_for_ticket(client: JiraClient, ticket: Ticket, jira_actor_name: str) -> int:
    db = SessionLocal()
    pushed = 0
    try:
        db_ticket = db.get(Ticket, ticket.id)
        if db_ticket is None or not db_ticket.jira_key:
            raise RuntimeError(f"ticket_missing_after_create:{ticket.id}")

        comments = (
            db.query(TicketComment)
            .filter(TicketComment.ticket_id == db_ticket.id)
            .order_by(TicketComment.created_at.asc())
            .all()
        )
        for comment in comments:
            rendered = _format_comment_text_for_jira(
                comment.content,
                author_name=comment.author,
                jira_actor_name=jira_actor_name,
            )
            created = client._request(  # noqa: SLF001
                "POST",
                f"/rest/api/3/issue/{db_ticket.jira_key}/comment",
                json={"body": _adf_from_text(rendered)},
            )
            comment.jira_comment_id = str(created.get("id") or "").strip() or None
            comment.jira_created_at = parse_jira_datetime(str(created.get("created") or "")) or comment.jira_created_at
            comment.jira_updated_at = parse_jira_datetime(str(created.get("updated") or "")) or comment.jira_updated_at
            comment.external_comment_id = comment.jira_comment_id
            comment.external_source = "jira"
            comment.external_updated_at = comment.jira_updated_at
            comment.raw_payload = created
            db.add(comment)
            pushed += 1
        db.commit()
    finally:
        db.close()
    return pushed


def push_local_dataset_to_jira(client: JiraClient) -> dict[str, Any]:
    jira_actor_name = str((client.get_myself() or {}).get("displayName") or "").strip()
    summary: list[dict[str, Any]] = []
    pushed_comments = 0

    db = SessionLocal()
    try:
        tickets = db.query(Ticket).order_by(Ticket.created_at.asc(), Ticket.id.asc()).all()
    finally:
        db.close()

    for seeded in tickets:
        db = SessionLocal()
        try:
            ticket = db.get(Ticket, seeded.id)
            if ticket is None:
                raise RuntimeError(f"missing_local_ticket:{seeded.id}")

            jira_key = create_jira_issue_for_ticket(ticket)
            if not jira_key:
                raise RuntimeError(f"jira_create_failed:{ticket.id}")

            details = client.get_issue(jira_key, fields="created,updated,status,summary,comment")
            now = dt.datetime.now(dt.timezone.utc)
            ticket.jira_key = jira_key
            ticket.jira_issue_id = str(details.get("id") or "").strip() or None
            ticket.jira_created_at = parse_jira_datetime(str(((details.get("fields") or {}).get("created") or ""))) or now
            ticket.jira_updated_at = parse_jira_datetime(str(((details.get("fields") or {}).get("updated") or ""))) or now
            ticket.external_id = jira_key
            ticket.external_source = "jira"
            ticket.external_updated_at = ticket.jira_updated_at
            ticket.last_synced_at = now
            db.add(ticket)
            db.commit()
            db.refresh(ticket)

            sync_jira_issue_for_ticket(ticket)
            converge_issue_status(client, ticket)
        finally:
            db.close()

        pushed_comments += push_comments_for_ticket(client, seeded, jira_actor_name)

        db = SessionLocal()
        try:
            ticket = db.get(Ticket, seeded.id)
            if ticket is None or not ticket.jira_key:
                raise RuntimeError(f"ticket_missing_after_comment_push:{seeded.id}")
            issue = client.get_issue(
                ticket.jira_key,
                fields="summary,status,priority,assignee,reporter,duedate,comment",
            )
            fields = issue.get("fields") or {}
            summary.append(
                {
                    "ticket_id": ticket.id,
                    "jira_key": ticket.jira_key,
                    "jira_status": str(((fields.get("status") or {}).get("name") or "")).strip(),
                    "jira_due": str(fields.get("duedate") or "").strip() or None,
                    "jira_comments": int(((fields.get("comment") or {}).get("total") or 0)),
                }
            )
        finally:
            db.close()

    return {"tickets": summary, "comments_pushed": pushed_comments}


def verify_counts(client: JiraClient, project_key: str) -> dict[str, Any]:
    jira_issues = fetch_project_issue_summaries(client, project_key)
    db = SessionLocal()
    try:
        local_tickets = db.query(Ticket).count()
        local_comments = db.query(TicketComment).count()
        linked_local_tickets = db.query(Ticket).filter(Ticket.jira_key.isnot(None)).count()
        linked_local_comments = db.query(TicketComment).filter(TicketComment.jira_comment_id.isnot(None)).count()
    finally:
        db.close()
    return {
        "project_key": project_key,
        "jira_issues": len(jira_issues),
        "local_tickets": local_tickets,
        "local_comments": local_comments,
        "linked_local_tickets": linked_local_tickets,
        "linked_local_comments": linked_local_comments,
    }


def main() -> int:
    project_key = settings.JIRA_PROJECT_KEY.strip()
    if not project_key:
        raise RuntimeError("missing_jira_project_key")

    client = JiraClient()

    print("Backing up current Jira project issue summaries...")
    backup = write_backup(client, project_key)
    print(f"Backup written: {backup}")

    print("Resetting local Jira linkage fields...")
    reset_local_jira_links()

    print(f"Deleting existing Jira issues in project {project_key}...")
    deleted_keys = purge_jira_project(client, project_key)
    print(f"Deleted Jira issues: {len(deleted_keys)}")

    print("Pushing current local dataset to Jira/JSM...")
    push_summary = push_local_dataset_to_jira(client)

    print("Running quick verification...")
    verification = verify_counts(client, project_key)

    payload = {
        "backup_path": str(backup),
        "deleted_jira_issues": len(deleted_keys),
        "push_summary": push_summary,
        "verification": verification,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
