"""Jira knowledge-base helpers built from existing issue comments."""

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
_snapshot_comments: list[dict[str, str]] = []


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
            "fields": "summary,comment",
        },
    )
    response.raise_for_status()
    data = response.json()
    issues = data.get("issues")
    return list(issues or [])


def _extract_issue_comments(issue: dict[str, Any]) -> list[dict[str, str]]:
    key = str(issue.get("key") or "").strip()
    fields = issue.get("fields") or {}
    summary = str(fields.get("summary") or "").strip()
    comment_field = fields.get("comment") or {}
    comments = list(comment_field.get("comments") or [])
    if not key or not summary or not comments:
        return []

    max_comments = max(1, settings.JIRA_KB_MAX_COMMENTS_PER_ISSUE)
    selected = comments[-max_comments:]
    rows: list[dict[str, str]] = []
    for comment in selected:
        text = _normalize_comment_text(comment.get("body"))
        if not text:
            continue
        author_data = comment.get("author") or {}
        author = str(author_data.get("displayName") or author_data.get("emailAddress") or "Unknown").strip()
        created = str(comment.get("created") or "")
        rows.append(
            {
                "issue_key": key,
                "summary": summary,
                "comment": _truncate(text),
                "author": author,
                "created": created,
            }
        )
    return rows


def _fetch_comments_snapshot() -> list[dict[str, str]]:
    if not settings.jira_kb_ready:
        return []

    with httpx.Client(
        timeout=30,
        auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    ) as client:
        issues = _fetch_issues_with_comments(client)

    comments: list[dict[str, str]] = []
    for issue in issues:
        comments.extend(_extract_issue_comments(issue))
    return comments


def _get_snapshot() -> list[dict[str, str]]:
    global _snapshot_expires_at, _snapshot_comments

    if not settings.jira_kb_ready:
        return []

    now = _utcnow()
    with _snapshot_lock:
        if _snapshot_expires_at and now < _snapshot_expires_at and _snapshot_comments:
            return list(_snapshot_comments)

        existing = list(_snapshot_comments)
        try:
            fresh = _fetch_comments_snapshot()
        except Exception as exc:
            logger.warning("Jira KB sync failed: %s", exc)
            if existing:
                _snapshot_expires_at = now + dt.timedelta(seconds=60)
                return existing
            return []

        _snapshot_comments = fresh
        ttl = max(30, settings.JIRA_KB_CACHE_SECONDS)
        _snapshot_expires_at = now + dt.timedelta(seconds=ttl)
        return list(_snapshot_comments)


def _rank_comments(query: str, rows: list[dict[str, str]], *, limit: int) -> list[dict[str, str]]:
    if not rows:
        return []

    query_lower = (query or "").lower().strip()
    query_tokens = _normalize_tokens(query_lower)
    scored: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        searchable = f"{row['summary']} {row['comment']}".lower()
        score = _overlap_score(query_tokens, _normalize_tokens(searchable))
        if query_lower and query_lower in searchable:
            score += 0.25
        if score <= 0:
            continue
        scored.append((score, row))

    if not scored:
        return rows[:limit]

    scored.sort(key=lambda item: (item[0], item[1].get("created", "")), reverse=True)
    return [item[1] for item in scored[:limit]]


def build_jira_knowledge_block(query: str, *, lang: str, limit: int | None = None) -> str:
    """Return a compact prompt block built from existing Jira comments."""
    if not settings.jira_kb_ready:
        return ""
    query = (query or "").strip()
    if not query:
        return ""

    top_n = max(1, limit or settings.JIRA_KB_TOP_MATCHES)
    rows = _get_snapshot()
    matches = _rank_comments(query, rows, limit=top_n)
    if not matches:
        return ""

    if lang == "fr":
        header = "Connaissance JSM (tickets similaires via commentaires):"
        lines = [
            f"- [{row['issue_key']}] {row['summary']} | Commentaire: {row['comment']} (auteur: {row['author']})"
            for row in matches
        ]
    else:
        header = "JSM knowledge (similar tickets from comments):"
        lines = [
            f"- [{row['issue_key']}] {row['summary']} | Comment: {row['comment']} (author: {row['author']})"
            for row in matches
        ]
    return "\n".join([header, *lines])
