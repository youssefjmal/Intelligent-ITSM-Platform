"""Jira knowledge-base helpers built from existing Jira issue content."""

from __future__ import annotations

import datetime as dt
import logging
import re
from threading import Lock
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u00C0-\u024F]{3,}")
_SPACE_RE = re.compile(r"\s+")
MIN_SCORE = 0.15
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "your",
    "are",
    "but",
    "les",
    "des",
    "pour",
    "avec",
    "dans",
    "une",
    "sur",
    "est",
    "pas",
    "ticket",
    "incident",
    "comment",
}

_snapshot_lock = Lock()
_snapshot_expires_at: dt.datetime | None = None
_snapshot_rows: list[dict[str, str]] = []


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_tokens(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {token for token in tokens if token not in _STOPWORDS}


def _overlap_score(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    common = len(query_tokens.intersection(text_tokens))
    return common / max(1, min(len(query_tokens), len(text_tokens)))


def _text_from_adf(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(part for part in (_text_from_adf(child) for child in node) if part)
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


def _normalize_comment_text(raw_body: Any) -> str:
    if isinstance(raw_body, str):
        text = raw_body
    else:
        text = _text_from_adf(raw_body)
    return _SPACE_RE.sub(" ", text).strip()


def _truncate(text: str, *, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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


def _extract_issue_kb_rows(issue: dict[str, Any]) -> list[dict[str, str]]:
    key = str(issue.get("key") or "").strip()
    fields = issue.get("fields") or {}
    summary = str(fields.get("summary") or "").strip()
    if not key or not summary:
        return []

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

    comment_field = fields.get("comment") or {}
    comments = list(comment_field.get("comments") or [])
    if not comments:
        return []

    max_comments = max(1, settings.JIRA_KB_MAX_COMMENTS_PER_ISSUE)
    selected = comments[-max_comments:]
    rows: list[dict[str, str]] = []
    for comment in selected:
        text = _normalize_comment_text(comment.get("body"))
        if not text:
            continue
        author_data = comment.get("author") or {}
        author = str(author_data.get("displayName") or "Unknown").strip()
        created = str(comment.get("created") or "")
        rows.append(
            {
                "issue_key": key,
                "summary": summary,
                "description": description,
                "comment": _truncate(text),
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
    return rows


def _fetch_kb_snapshot() -> list[dict[str, str]]:
    if not settings.jira_kb_ready:
        return []

    with httpx.Client(
        timeout=30,
        auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    ) as client:
        issues = _fetch_issues_with_comments(client)

    rows: list[dict[str, str]] = []
    for issue in issues:
        rows.extend(_extract_issue_kb_rows(issue))
    return rows


def _normalize_filter_values(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_filter_values(item))
        return values
    value = str(raw).strip().lower()
    return [value] if value else []


def _csv_values(text: str) -> list[str]:
    return [part.strip().lower() for part in (text or "").split(",") if part.strip()]


def _matches_values(candidates: list[str], expected_values: list[str]) -> bool:
    if not expected_values:
        return True
    cleaned_candidates = [candidate for candidate in candidates if candidate]
    if not cleaned_candidates:
        return False
    for expected in expected_values:
        for candidate in cleaned_candidates:
            if expected in candidate or candidate in expected:
                return True
    return False


def _passes_filters(row: dict[str, str], filters: dict | None) -> bool:
    if not filters:
        return True

    issuetype = str(row.get("issuetype") or "").strip().lower()
    labels = _csv_values(str(row.get("labels") or ""))
    components = _csv_values(str(row.get("components") or ""))
    priority = str(row.get("priority") or "").strip().lower()
    status = str(row.get("status") or "").strip().lower()

    category_values = _normalize_filter_values(filters.get("category"))
    if category_values and not _matches_values([issuetype, *labels], category_values):
        return False

    service_values = _normalize_filter_values(filters.get("service"))
    if service_values and not _matches_values([issuetype, *labels], service_values):
        return False

    component_values = _normalize_filter_values(filters.get("component"))
    if component_values and not _matches_values(components, component_values):
        return False

    priority_values = _normalize_filter_values(filters.get("priority"))
    if priority_values and not _matches_values([priority], priority_values):
        return False

    status_values = _normalize_filter_values(filters.get("status"))
    if status_values and not _matches_values([status], status_values):
        return False

    return True


def _get_snapshot() -> list[dict[str, str]]:
    global _snapshot_expires_at, _snapshot_rows

    if not settings.jira_kb_ready:
        return []

    now = _utcnow()
    with _snapshot_lock:
        if _snapshot_expires_at and now < _snapshot_expires_at and _snapshot_rows:
            return list(_snapshot_rows)

        existing = list(_snapshot_rows)
        try:
            fresh = _fetch_kb_snapshot()
        except Exception as exc:
            logger.warning("Jira KB sync failed: %s", exc)
            if existing:
                _snapshot_expires_at = now + dt.timedelta(seconds=60)
                return existing
            return []

        _snapshot_rows = fresh
        ttl = max(30, settings.JIRA_KB_CACHE_SECONDS)
        _snapshot_expires_at = now + dt.timedelta(seconds=ttl)
        return list(_snapshot_rows)


def _rank_comments(
    query: str,
    rows: list[dict[str, str]],
    *,
    limit: int,
    filters: dict | None = None,
) -> list[dict[str, str]]:
    if not rows:
        return []

    filtered_rows = [row for row in rows if _passes_filters(row, filters)]
    if not filtered_rows:
        return []

    query_lower = (query or "").lower().strip()
    query_tokens = _normalize_tokens(query_lower)
    scored: list[tuple[float, dict[str, str]]] = []
    has_filter_values = bool(filters and any(_normalize_filter_values(value) for value in filters.values()))
    for row in filtered_rows:
        searchable = " ".join(
            (
                row.get("summary", ""),
                row.get("description", ""),
                row.get("comment", ""),
                row.get("labels", ""),
                row.get("components", ""),
                row.get("priority", ""),
                row.get("status", ""),
                row.get("issuetype", ""),
            )
        ).lower()
        score = _overlap_score(query_tokens, _normalize_tokens(searchable))
        if query_lower and query_lower in searchable:
            score += 0.25
        if has_filter_values:
            score += 0.1
        if score < MIN_SCORE:
            continue
        scored.append((score, row))

    if not scored:
        return []

    scored.sort(key=lambda item: (item[0], item[1].get("created", "")), reverse=True)
    return [item[1] for item in scored[:limit]]


def build_jira_knowledge_block(
    query: str,
    *,
    lang: str,
    limit: int | None = None,
    filters: dict | None = None,
) -> str:
    """Return a compact prompt block built from Jira issue summaries, descriptions, and comments."""
    if not settings.jira_kb_ready:
        return ""
    query = (query or "").strip()
    if not query:
        return ""

    top_n = max(1, limit or settings.JIRA_KB_TOP_MATCHES)
    rows = _get_snapshot()
    matches = _rank_comments(query, rows, limit=top_n, filters=filters)
    if not matches:
        return ""

    if lang == "fr":
        header = "Connaissance JSM (tickets similaires via contenu Jira):"
        lines = [
            (
                f"- [{row['issue_key']}] {row['summary']} "
                f"({row.get('priority') or '-'} | {row.get('status') or '-'} | "
                f"Composants: {row.get('components') or '-'}) | "
                f"Desc: {_truncate(row.get('description', ''), limit=180)} | "
                f"Commentaire: {_truncate(row.get('comment', ''), limit=220)} "
                f"(auteur: {row.get('author') or 'Unknown'})"
            )
            for row in matches
        ]
    else:
        header = "JSM knowledge (similar tickets from Jira content):"
        lines = [
            (
                f"- [{row['issue_key']}] {row['summary']} "
                f"({row.get('priority') or '-'} | {row.get('status') or '-'} | "
                f"Components: {row.get('components') or '-'}) | "
                f"Desc: {_truncate(row.get('description', ''), limit=180)} | "
                f"Comment: {_truncate(row.get('comment', ''), limit=220)} "
                f"(author: {row.get('author') or 'Unknown'})"
            )
            for row in matches
        ]
    return "\n".join([header, *lines])
