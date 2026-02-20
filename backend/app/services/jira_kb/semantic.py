"""Semantic ingestion and retrieval helpers for Jira KB."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import time
from typing import Any

from sqlalchemy import select, text as sa_text, tuple_

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.kb_chunk import KBChunk
from app.services.embeddings import compute_embedding, search_kb
from app.services.jira_kb import state
from app.services.jira_kb.adf import _normalize_comment_text
from app.services.jira_kb.constants import (
    EMBEDDING_REFRESH_TIME_BUDGET_SECONDS,
    INMEMORY_SEMANTIC_EMBEDDING_BUDGET,
    LOGGER_NAME,
    MAX_COMMENT_EMBEDDINGS_PER_REFRESH,
    MAX_ISSUE_EMBEDDINGS_PER_REFRESH,
    MIN_SEMANTIC_SCORE,
    _SPACE_RE,
)
from app.services.jira_kb.filters import _passes_filters
from app.services.jira_kb.scoring import _rank_comments, _status_category_bias

logger = logging.getLogger(LOGGER_NAME)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _kb_chunks_table_ready(*, ttl_seconds: int = 120) -> bool:
    now = _utcnow()
    with state._snapshot_lock:
        if (
            state._kb_chunks_ready is not None
            and state._kb_chunks_checked_at is not None
            and (now - state._kb_chunks_checked_at).total_seconds() < ttl_seconds
        ):
            return bool(state._kb_chunks_ready)

    db = SessionLocal()
    try:
        table = str(KBChunk.__tablename__ or "").strip() or "kb_chunks"
        regclass = db.execute(
            sa_text("SELECT to_regclass(:table_name)"),
            {"table_name": f"public.{table}"},
        ).scalar()
        ready = bool(regclass)
    except Exception:
        ready = False
    finally:
        db.close()

    with state._snapshot_lock:
        state._kb_chunks_ready = ready
        state._kb_chunks_checked_at = now
    return ready


def _content_hash(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _embedding_time_budget_exceeded(*, started_at: float) -> bool:
    return (time.monotonic() - started_at) >= EMBEDDING_REFRESH_TIME_BUDGET_SECONDS


def _sync_kb_chunks(*, issue_rows: list[dict[str, str]], comment_rows: list[dict[str, str]]) -> None:
    if not _kb_chunks_table_ready():
        return

    issue_candidates: list[tuple[dict[str, str], str, str]] = []
    for row in issue_rows:
        content = _normalize_comment_text(row.get("issue_content") or "")
        if not content:
            continue
        issue_candidates.append((row, content, _content_hash(content)))

    comment_candidates: list[tuple[dict[str, str], str, str]] = []
    for row in comment_rows:
        content = _normalize_comment_text(row.get("comment") or "")
        if not content:
            continue
        comment_candidates.append((row, content, _content_hash(content)))

    if not issue_candidates and not comment_candidates:
        return

    db = SessionLocal()
    try:
        wrote = False
        sync_started_at = time.monotonic()
        issue_embeddings = 0
        comment_embeddings = 0
        issue_ids = [str(row.get("issue_id") or "").strip() for row, _, _ in issue_candidates if str(row.get("issue_id") or "").strip()]
        existing_issue_chunks: dict[str, KBChunk] = {}
        if issue_ids:
            existing_issue_rows = db.execute(
                select(KBChunk).where(
                    KBChunk.source_type == "jira_issue",
                    KBChunk.jira_issue_id.in_(issue_ids),
                    KBChunk.comment_id.is_(None),
                )
            ).scalars().all()
            existing_issue_chunks = {str(chunk.jira_issue_id or ""): chunk for chunk in existing_issue_rows if str(chunk.jira_issue_id or "")}

        for row, content, content_hash in issue_candidates:
            issue_id = str(row.get("issue_id") or "").strip()
            issue_key = str(row.get("issue_key") or "").strip()
            if not issue_id or not issue_key:
                continue
            existing_issue = existing_issue_chunks.get(issue_id)
            if existing_issue is not None and str(existing_issue.content_hash or "") == content_hash:
                continue

            if issue_embeddings >= MAX_ISSUE_EMBEDDINGS_PER_REFRESH or _embedding_time_budget_exceeded(
                started_at=sync_started_at
            ):
                break
            try:
                embedding = compute_embedding(content)
                issue_embeddings += 1
            except Exception as exc:
                logger.warning(
                    "Jira KB issue embedding failed for %s: %s",
                    issue_key or "-",
                    exc,
                )
                continue

            metadata = {
                "summary": row.get("summary") or "",
                "description": row.get("description") or "",
                "priority": row.get("priority") or "",
                "status": row.get("status") or "",
                "status_category": row.get("status_category") or "",
                "issuetype": row.get("issuetype") or "",
                "components": row.get("components") or "",
                "labels": row.get("labels") or "",
            }
            if existing_issue is not None:
                existing_issue.jira_key = issue_key
                existing_issue.comment_id = None
                existing_issue.content = content
                existing_issue.content_hash = content_hash
                existing_issue.metadata_json = metadata
                existing_issue.embedding = embedding
                existing_issue.updated_at = _utcnow()
                db.add(existing_issue)
                db.flush()
            else:
                existing_issue = KBChunk(
                    source_type="jira_issue",
                    jira_issue_id=issue_id,
                    jira_key=issue_key,
                    comment_id=None,
                    content=content,
                    content_hash=content_hash,
                    metadata_json=metadata,
                    embedding=embedding,
                )
                db.add(existing_issue)
                db.flush()
                existing_issue_chunks[issue_id] = existing_issue
            wrote = True

        existing_comment_chunks: dict[tuple[str, str], KBChunk] = {}
        comment_ids = [str(row.get("comment_id") or "").strip() for row, _, _ in comment_candidates if str(row.get("comment_id") or "").strip()]
        pair_values = sorted(
            {
                (
                    str(row.get("issue_key") or "").strip(),
                    str(row.get("comment_id") or "").strip(),
                )
                for row, _, _ in comment_candidates
                if str(row.get("issue_key") or "").strip() and str(row.get("comment_id") or "").strip()
            }
        )
        if pair_values and comment_ids:
            existing_comment_rows: list[KBChunk] = []
            try:
                existing_comment_rows = db.execute(
                    select(KBChunk)
                    .where(
                        KBChunk.source_type == "jira_comment",
                        tuple_(KBChunk.jira_key, KBChunk.comment_id).in_(pair_values),
                    )
                    .order_by(KBChunk.updated_at.desc(), KBChunk.created_at.desc(), KBChunk.id.desc())
                ).scalars().all()
            except Exception:
                existing_comment_rows = db.execute(
                    select(KBChunk)
                    .where(
                        KBChunk.source_type == "jira_comment",
                        KBChunk.comment_id.in_(comment_ids),
                    )
                    .order_by(KBChunk.updated_at.desc(), KBChunk.created_at.desc(), KBChunk.id.desc())
                ).scalars().all()
            for chunk in existing_comment_rows:
                jira_key = str(chunk.jira_key or "").strip()
                comment_id = str(chunk.comment_id or "").strip()
                if not jira_key or not comment_id:
                    continue
                key = (jira_key, comment_id)
                if key not in existing_comment_chunks:
                    existing_comment_chunks[key] = chunk

        for row, content, content_hash in comment_candidates:
            jira_key = str(row.get("issue_key") or "").strip()
            comment_id = str(row.get("comment_id") or "").strip()
            existing_comment = existing_comment_chunks.get((jira_key, comment_id)) if jira_key and comment_id else None
            if existing_comment is not None and str(existing_comment.content_hash or "") == content_hash:
                continue

            if comment_embeddings >= MAX_COMMENT_EMBEDDINGS_PER_REFRESH or _embedding_time_budget_exceeded(
                started_at=sync_started_at
            ):
                break
            try:
                embedding = compute_embedding(content)
                comment_embeddings += 1
            except Exception as exc:
                logger.warning(
                    "Jira KB embedding failed for %s/%s: %s",
                    row.get("issue_key") or "-",
                    row.get("comment_id") or "-",
                    exc,
                )
                continue

            metadata = {
                "summary": row.get("summary") or "",
                "description": row.get("description") or "",
                "author": row.get("author") or "",
                "created": row.get("created") or "",
                "priority": row.get("priority") or "",
                "status": row.get("status") or "",
                "status_category": row.get("status_category") or "",
                "issuetype": row.get("issuetype") or "",
                "components": row.get("components") or "",
                "labels": row.get("labels") or "",
            }
            chunk = existing_comment
            if chunk is None:
                chunk = KBChunk(
                    source_type="jira_comment",
                    jira_issue_id=row.get("issue_id") or None,
                    jira_key=jira_key or None,
                    comment_id=comment_id or None,
                    content=content,
                    content_hash=content_hash,
                    metadata_json=metadata,
                    embedding=embedding,
                )
            else:
                chunk.jira_issue_id = row.get("issue_id") or None
                chunk.jira_key = jira_key or None
                chunk.comment_id = comment_id or None
                chunk.content = content
                chunk.content_hash = content_hash
                chunk.metadata_json = metadata
                chunk.embedding = embedding
                chunk.updated_at = _utcnow()
            db.add(chunk)
            db.flush()
            if jira_key and comment_id:
                existing_comment_chunks[(jira_key, comment_id)] = chunk
            wrote = True

        if wrote:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _row_from_semantic_match(match: dict[str, Any]) -> dict[str, str]:
    raw_meta = match.get("metadata")
    if not isinstance(raw_meta, dict):
        raw_meta = match.get("metadata_json")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    return {
        "issue_id": str(match.get("jira_issue_id") or ""),
        "issue_key": str(match.get("jira_key") or meta.get("jira_key") or ""),
        "summary": str(meta.get("summary") or ""),
        "description": str(meta.get("description") or ""),
        "comment_id": str(match.get("comment_id") or ""),
        "comment": str(match.get("content") or ""),
        "author": str(meta.get("author") or ""),
        "created": str(meta.get("created") or ""),
        "priority": str(meta.get("priority") or ""),
        "status": str(meta.get("status") or ""),
        "status_category": str(meta.get("status_category") or ""),
        "issuetype": str(meta.get("issuetype") or ""),
        "components": str(meta.get("components") or ""),
        "labels": str(meta.get("labels") or ""),
    }


def _rank_comments_semantic(
    query: str,
    *,
    limit: int,
    filters: dict | None = None,
    min_score: float = MIN_SEMANTIC_SCORE,
) -> list[dict[str, str]]:
    if not _kb_chunks_table_ready():
        return []

    db = SessionLocal()
    try:
        raw_matches = search_kb(db, query, top_k=max(limit * 3, limit), source_type="jira_comment")
    except Exception as exc:
        logger.warning("Jira KB semantic search failed: %s", exc)
        return []
    finally:
        db.close()

    scored: list[tuple[float, dict[str, str]]] = []
    for match in raw_matches:
        row = _row_from_semantic_match(match)
        if not row.get("issue_key") or not row.get("comment"):
            continue
        if not _passes_filters(row, filters):
            continue
        score = float(match.get("score") or 0.0)
        score += _status_category_bias(row)
        if score < min_score:
            continue
        scored.append((score, row))

    if not scored:
        return []

    scored.sort(key=lambda item: (item[0], item[1].get("created", "")), reverse=True)
    return [item[1] for item in scored[:limit]]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    value = dot / (left_norm * right_norm)
    return max(-1.0, min(1.0, float(value)))


def _rank_comments_semantic_inmemory(
    query: str,
    rows: list[dict[str, str]],
    *,
    limit: int,
    filters: dict | None = None,
    min_score: float = MIN_SEMANTIC_SCORE,
) -> list[dict[str, str]]:
    if not rows:
        return []

    preselected = _rank_comments(query, rows, limit=max(limit * 3, 9), filters=filters)
    if not preselected:
        preselected = [row for row in rows if _passes_filters(row, filters)][: max(limit * 3, 9)]
    if not preselected:
        return []

    try:
        query_vec = compute_embedding(query)
    except Exception as exc:
        logger.warning("Jira KB in-memory semantic query embedding failed: %s", exc)
        return []

    scored: list[tuple[float, dict[str, str]]] = []
    for row in preselected[:INMEMORY_SEMANTIC_EMBEDDING_BUDGET]:
        content = _normalize_comment_text(row.get("comment") or "")
        if not content:
            continue
        hash_key = _content_hash(content)
        with state._embedding_cache_lock:
            vector = state._inmemory_embedding_cache.get(hash_key)
        if vector is None:
            try:
                vector = compute_embedding(content)
            except Exception:
                continue
            with state._embedding_cache_lock:
                state._inmemory_embedding_cache[hash_key] = vector

        score = _cosine_similarity(query_vec, vector)
        score += _status_category_bias(row)
        if score < min_score:
            continue
        scored.append((score, row))

    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1].get("created", "")), reverse=True)
    return [item[1] for item in scored[:limit]]


def _merge_rows(primary: list[dict[str, str]], secondary: list[dict[str, str]], *, limit: int) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in [*primary, *secondary]:
        key = (
            f"{row.get('issue_key') or ''}|{row.get('comment_id') or ''}|"
            f"{_content_hash(row.get('comment') or '')}"
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged
