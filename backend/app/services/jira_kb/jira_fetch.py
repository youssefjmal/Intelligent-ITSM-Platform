"""Jira API fetch and row extraction helpers for Jira KB."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import httpx

from app.core.config import settings
from app.services.jira_kb.adf import _normalize_comment_text
from app.services.jira_kb.constants import (
    ISSUE_CONTEXT_DESCRIPTION_EMBED_LIMIT,
    ISSUE_CONTEXT_EMBED_LIMIT,
)
from app.services.jira_kb.formatting import _truncate
from app.services.jira_kb.scoring import _select_best_comments


def _build_jql() -> str:
    key = settings.JIRA_PROJECT_KEY.strip()
    if key:
        return f'project = "{key}" ORDER BY updated DESC'
    return "updated IS NOT EMPTY ORDER BY updated DESC"


def _fetch_issues_with_comments(client: httpx.Client) -> list[dict[str, Any]]:
    url = f"{settings.JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    response = client.get(
        url,
        params={
            "jql": _build_jql(),
            "maxResults": max(1, settings.JIRA_KB_MAX_ISSUES),
            "fields": "summary,description,comment,priority,status,components,labels,issuetype",
        },
    )
    response.raise_for_status()
    data = response.json()
    issues = data.get("issues")
    return list(issues or [])


def _build_issue_context_content(
    *,
    summary: str,
    description: str,
    issuetype: str,
    priority: str,
    status: str,
    components: str,
    labels: str,
) -> str:
    summary_text = _normalize_comment_text(summary)
    issuetype_text = _normalize_comment_text(issuetype)
    priority_text = _normalize_comment_text(priority)
    status_text = _normalize_comment_text(status)
    components_text = _normalize_comment_text(components)
    labels_text = _normalize_comment_text(labels)
    description_text = _normalize_comment_text(description)[:ISSUE_CONTEXT_DESCRIPTION_EMBED_LIMIT]

    tail_block = "\n".join(
        [
            issuetype_text,
            priority_text,
            status_text,
            components_text,
            labels_text,
        ]
    )
    reserved = len(summary_text) + len(tail_block) + 2
    allowed_description = max(0, ISSUE_CONTEXT_EMBED_LIMIT - reserved)
    if len(description_text) > allowed_description:
        description_text = description_text[:allowed_description].rstrip()

    content = _normalize_comment_text(
        "\n".join(
            [
                summary_text,
                description_text,
                tail_block,
            ]
        )
    )
    if len(content) > ISSUE_CONTEXT_EMBED_LIMIT:
        return content[:ISSUE_CONTEXT_EMBED_LIMIT].rstrip()
    return content


def _parse_jira_datetime(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = f"{normalized[:-5]}{normalized[-5:-2]}:{normalized[-2:]}"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _extract_issue_kb_rows(issue: dict[str, Any]) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    issue_id = str(issue.get("id") or "").strip()
    key = str(issue.get("key") or "").strip()
    fields = issue.get("fields") or {}
    summary = str(fields.get("summary") or "").strip()
    if not key or not summary:
        return None, []

    description_raw = fields.get("description")
    description_text = _normalize_comment_text(description_raw)
    description = _truncate(description_text, limit=320) if description_text else ""
    priority = str((fields.get("priority") or {}).get("name") or "").strip()
    status_data = fields.get("status") or {}
    status = str(status_data.get("name") or "").strip()
    status_category = str((status_data.get("statusCategory") or {}).get("name") or "").strip()
    issuetype = str((fields.get("issuetype") or {}).get("name") or "").strip()

    component_names = [
        str(component.get("name") or "").strip()
        for component in list(fields.get("components") or [])
        if isinstance(component, dict) and str(component.get("name") or "").strip()
    ]
    components = ", ".join(component_names)
    labels = ", ".join(str(label).strip() for label in list(fields.get("labels") or []) if str(label).strip())

    issue_content = _build_issue_context_content(
        summary=summary,
        description=description_text,
        issuetype=issuetype,
        priority=priority,
        status=status,
        components=components,
        labels=labels,
    )
    issue_row: dict[str, str] = {
        "issue_id": issue_id,
        "issue_key": key,
        "summary": summary,
        "description": description,
        "issue_content": issue_content,
        "priority": priority,
        "status": status,
        "status_category": status_category,
        "issuetype": issuetype,
        "components": components,
        "labels": labels,
    }

    comment_field = fields.get("comment") or {}
    comments = list(comment_field.get("comments") or [])
    max_comments = max(1, settings.JIRA_KB_MAX_COMMENTS_PER_ISSUE)
    selected = _select_best_comments(comments, limit=max_comments)
    rows: list[dict[str, str]] = []
    for comment, text in selected:
        comment_id = str(comment.get("id") or "").strip()
        author_data = comment.get("author") or {}
        author = str(author_data.get("displayName") or "Unknown").strip()
        created = str(comment.get("created") or "")
        rows.append(
            {
                "issue_id": issue_id,
                "issue_key": key,
                "summary": summary,
                "description": description,
                "comment_id": comment_id,
                "comment": text,
                "author": author,
                "created": created,
                "priority": priority,
                "status": status,
                "status_category": status_category,
                "issuetype": issuetype,
                "components": components,
                "labels": labels,
            }
        )
    return issue_row, rows
