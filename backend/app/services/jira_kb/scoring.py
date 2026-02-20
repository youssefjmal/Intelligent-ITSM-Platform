"""Scoring helpers for Jira KB lexical and comment quality ranking."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.services.jira_kb.adf import _adf_contains_type, _normalize_comment_text
from app.services.jira_kb.constants import (
    COMMENT_MIN_LENGTH,
    LOW_SIGNAL_SHORT_COMMENT_MAX_LENGTH,
    STATUS_COMPLETED_BONUS,
    STATUS_NEW_PENALTY,
    _HEX_ERROR_RE,
    _HIGH_SIGNAL_COMMENT_KEYWORDS,
    _LOW_SIGNAL_SHORT_COMMENT_PHRASES,
    _SPACE_RE,
    _STACK_TRACE_RE,
    _STOPWORDS,
    _TOKEN_RE,
    MIN_SCORE,
)
from app.services.jira_kb.filters import _normalize_filter_values, _passes_filters


def _normalize_tokens(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {token for token in tokens if token not in _STOPWORDS}


def _overlap_score(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    common = len(query_tokens.intersection(text_tokens))
    return common / max(1, min(len(query_tokens), len(text_tokens)))


def _is_low_value_comment(text: str) -> bool:
    normalized = _SPACE_RE.sub(" ", (text or "").strip()).lower()
    if not normalized:
        return True
    if len(normalized) < COMMENT_MIN_LENGTH:
        return True
    if len(normalized) >= LOW_SIGNAL_SHORT_COMMENT_MAX_LENGTH:
        return False
    return any(phrase in normalized for phrase in _LOW_SIGNAL_SHORT_COMMENT_PHRASES)


def _comment_is_internal_or_agent(comment: dict[str, Any]) -> bool:
    jsd_public = comment.get("jsdPublic")
    if jsd_public is False:
        return True
    author = comment.get("author") or {}
    account_type = str(author.get("accountType") or "").strip().lower()
    return bool(account_type and account_type != "customer")


def _comment_has_code_or_log_signal(comment: dict[str, Any], text: str) -> bool:
    body = comment.get("body")
    if isinstance(body, str):
        if "```" in body:
            return True
        if body.count("\n") >= 2:
            return True
    elif _adf_contains_type(body, "codeBlock"):
        return True

    compact = _SPACE_RE.sub(" ", (text or "").strip()).lower()
    if _HEX_ERROR_RE.search(compact):
        return True
    if _STACK_TRACE_RE.search(compact):
        return True
    return False


def _comment_quality_score(comment: dict[str, Any], text: str) -> float:
    compact = _SPACE_RE.sub(" ", (text or "").strip()).lower()
    if not compact:
        return 0.0

    score = 0.0
    if _comment_is_internal_or_agent(comment):
        score += 1.7
    else:
        score -= 0.2

    author = comment.get("author") or {}
    account_type = str(author.get("accountType") or "").strip().lower()
    if account_type == "customer":
        score -= 0.2
    elif account_type:
        score += 0.2

    length = len(compact)
    score += min(0.5, length / 1200.0)
    if length >= LOW_SIGNAL_SHORT_COMMENT_MAX_LENGTH:
        score += 0.2
    if length >= 240:
        score += 0.2

    keyword_hits = sum(1 for keyword in _HIGH_SIGNAL_COMMENT_KEYWORDS if keyword in compact)
    score += min(1.2, keyword_hits * 0.18)

    if _comment_has_code_or_log_signal(comment, compact):
        score += 1.0

    return score


def _select_best_comments(comments: list[dict[str, Any]], *, limit: int) -> list[tuple[dict[str, Any], str]]:
    if not comments:
        return []

    # Local import avoids import cycle while keeping behavior unchanged.
    from app.services.jira_kb.jira_fetch import _parse_jira_datetime

    max_items = max(1, int(limit))
    min_dt = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    max_dt = dt.datetime.max.replace(tzinfo=dt.timezone.utc)

    ranked: list[tuple[float, dt.datetime | None, dict[str, Any], str]] = []
    for comment in comments:
        text = _normalize_comment_text(comment.get("body"))
        if _is_low_value_comment(text):
            continue
        score = _comment_quality_score(comment, text)
        created_at = _parse_jira_datetime(comment.get("created"))
        ranked.append((score, created_at, comment, text))

    if not ranked:
        return []

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1] or min_dt,
            len(item[3]),
        ),
        reverse=True,
    )
    selected = ranked[:max_items]
    selected.sort(
        key=lambda item: (
            item[1] or max_dt,
            str((item[2] or {}).get("id") or ""),
        )
    )
    return [(item[2], item[3]) for item in selected]


def _status_category_bias(row: dict[str, str]) -> float:
    status_category = str(row.get("status_category") or "").strip().lower()
    if status_category in {"done", "resolved"}:
        return STATUS_COMPLETED_BONUS
    if status_category in {"to do", "todo", "new"}:
        return -STATUS_NEW_PENALTY
    return 0.0


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
        score += _status_category_bias(row)
        if score < MIN_SCORE:
            continue
        scored.append((score, row))

    if not scored:
        return []

    scored.sort(key=lambda item: (item[0], item[1].get("created", "")), reverse=True)
    return [item[1] for item in scored[:limit]]
