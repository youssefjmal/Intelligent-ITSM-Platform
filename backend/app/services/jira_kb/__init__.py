"""Jira knowledge-base helpers built from existing Jira issue content."""

from __future__ import annotations

from app.core.config import settings
from app.services.jira_kb.constants import MIN_SEMANTIC_SCORE
from app.services.jira_kb.formatting import _format_knowledge_block
from app.services.jira_kb.scoring import _rank_comments
from app.services.jira_kb.semantic import _merge_rows, _rank_comments_semantic, _rank_comments_semantic_inmemory
from app.services.jira_kb.snapshot import _get_snapshot


def build_jira_knowledge_block(
    query: str,
    *,
    lang: str,
    limit: int | None = None,
    filters: dict | None = None,
    semantic_only: bool = False,
    semantic_min_score: float | None = None,
) -> str:
    """Return a compact prompt block using semantic Jira comment retrieval."""
    if not settings.jira_kb_ready:
        return ""
    query = (query or "").strip()
    if not query:
        return ""

    top_n = max(1, limit or settings.JIRA_KB_TOP_MATCHES)
    if semantic_min_score is None:
        semantic_threshold = MIN_SEMANTIC_SCORE
    else:
        semantic_threshold = max(0.0, min(1.0, float(semantic_min_score)))
    rows = _get_snapshot()
    semantic_matches = _rank_comments_semantic(
        query,
        limit=top_n,
        filters=filters,
        min_score=semantic_threshold,
    )
    if not semantic_matches:
        semantic_matches = _rank_comments_semantic_inmemory(
            query,
            rows,
            limit=top_n,
            filters=filters,
            min_score=semantic_threshold,
        )
    if semantic_matches:
        lexical_matches = _rank_comments(query, rows, limit=max(top_n * 2, top_n), filters=filters)
        matches = _merge_rows(semantic_matches, lexical_matches, limit=top_n)
    elif semantic_only:
        matches = []
    else:
        matches = _rank_comments(query, rows, limit=top_n, filters=filters)
    if not matches:
        return ""

    return _format_knowledge_block(lang=lang, matches=matches)


__all__ = ["build_jira_knowledge_block"]
