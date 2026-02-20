"""Embedding generation and pgvector search helpers."""

from __future__ import annotations

import datetime as dt
import logging
import re
from threading import Lock
from typing import Any

import httpx
from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.kb_chunk import KBChunk

EMBEDDING_DIM = 768
_SPACE_RE = re.compile(r"\s+")
_SEARCH_READY_CACHE_TTL_SECONDS = 120
_search_ready_cache_lock = Lock()
_search_ready_cache_value: bool | None = None
_search_ready_cache_at: dt.datetime | None = None

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "")).strip()


def _to_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        raise RuntimeError("invalid_embedding_payload")
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive conversion
        raise RuntimeError("embedding_contains_non_numeric_values") from exc
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"embedding_dim_mismatch: expected={EMBEDDING_DIM} got={len(vector)}")
    return vector


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _kb_search_ready(db: Session) -> bool:
    global _search_ready_cache_value, _search_ready_cache_at

    now = _utcnow()
    with _search_ready_cache_lock:
        if (
            _search_ready_cache_value is not None
            and _search_ready_cache_at is not None
            and (now - _search_ready_cache_at).total_seconds() < _SEARCH_READY_CACHE_TTL_SECONDS
        ):
            return bool(_search_ready_cache_value)

    try:
        has_vector = bool(db.execute(sa_text("SELECT 1 FROM pg_extension WHERE extname='vector'")).scalar())
        has_table = bool(db.execute(sa_text("SELECT to_regclass('public.kb_chunks')")).scalar())
        ready = has_vector and has_table
    except Exception:
        ready = False

    with _search_ready_cache_lock:
        _search_ready_cache_value = ready
        _search_ready_cache_at = now
    return ready


def compute_embedding(text: str) -> list[float]:
    """Compute an embedding using Ollama /api/embeddings."""
    normalized = _normalize_text(text)
    if not normalized:
        raise ValueError("empty_text_for_embedding")

    if settings.OLLAMA_EMBEDDING_DIM != EMBEDDING_DIM:
        raise RuntimeError(
            f"invalid_config_embedding_dim: expected={EMBEDDING_DIM} got={settings.OLLAMA_EMBEDDING_DIM}"
        )

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
    payload = {
        "model": settings.OLLAMA_EMBED_MODEL,
        "prompt": normalized,
    }
    timeout = httpx.Timeout(connect=5.0, read=45.0, write=20.0, pool=5.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError("ollama_embedding_request_failed") from exc

    return _to_float_list(data.get("embedding"))


def upsert_kb_chunk(
    db: Session,
    *,
    source_type: str,
    jira_issue_id: str | None,
    jira_key: str | None,
    comment_id: str | None,
    content: str,
    content_hash: str,
    metadata: dict[str, Any] | None,
    embedding: list[float],
) -> KBChunk:
    """Insert or update a KB chunk by its deterministic content hash."""
    vector = _to_float_list(embedding)
    normalized_content = _normalize_text(content)
    if not normalized_content:
        raise ValueError("empty_chunk_content")

    normalized_jira_key = str(jira_key or "").strip() or None
    normalized_comment_id = str(comment_id or "").strip() or None

    if source_type == "jira_comment" and normalized_jira_key and normalized_comment_id:
        existing_comment = db.execute(
            select(KBChunk).where(
                KBChunk.source_type == "jira_comment",
                KBChunk.jira_key == normalized_jira_key,
                KBChunk.comment_id == normalized_comment_id,
            )
        ).scalar_one_or_none()
        if existing_comment:
            existing_comment.source_type = source_type
            existing_comment.jira_issue_id = jira_issue_id
            existing_comment.jira_key = normalized_jira_key
            existing_comment.comment_id = normalized_comment_id
            existing_comment.content = normalized_content
            existing_comment.content_hash = content_hash
            existing_comment.metadata_json = metadata
            existing_comment.embedding = vector
            existing_comment.updated_at = dt.datetime.now(dt.timezone.utc)
            db.add(existing_comment)
            db.flush()
            return existing_comment

    existing = db.execute(select(KBChunk).where(KBChunk.content_hash == content_hash)).scalar_one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    if existing:
        existing.source_type = source_type
        existing.jira_issue_id = jira_issue_id
        existing.jira_key = normalized_jira_key
        existing.comment_id = normalized_comment_id
        existing.content = normalized_content
        existing.metadata_json = metadata
        existing.embedding = vector
        existing.updated_at = now
        db.add(existing)
        db.flush()
        return existing

    chunk = KBChunk(
        source_type=source_type,
        jira_issue_id=jira_issue_id,
        jira_key=normalized_jira_key,
        comment_id=normalized_comment_id,
        content=normalized_content,
        content_hash=content_hash,
        metadata_json=metadata,
        embedding=vector,
        created_at=now,
        updated_at=now,
    )
    db.add(chunk)
    db.flush()
    return chunk


def _match_to_result(chunk: KBChunk, *, distance: float | None = None) -> dict[str, Any]:
    distance_value = float(distance if distance is not None else 1.0)
    score = max(0.0, min(1.0, 1.0 - distance_value))
    return {
        "score": score,
        "distance": distance_value,
        "source_type": chunk.source_type,
        "jira_key": chunk.jira_key,
        "jira_issue_id": chunk.jira_issue_id,
        "comment_id": chunk.comment_id,
        "content": chunk.content,
        "metadata": chunk.metadata_json or {},
    }


def search_kb(
    db: Session,
    query: str,
    top_k: int = 5,
    *,
    source_type: str | None = None,
    jira_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search KB chunks with cosine similarity over pgvector embeddings."""
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return []
    if not _kb_search_ready(db):
        return []

    limit = max(1, min(int(top_k), 50))
    normalized_source_type = str(source_type or "").strip()
    normalized_keys = [str(key or "").strip() for key in (jira_keys or []) if str(key or "").strip()]
    query_vector = compute_embedding(normalized_query)
    distance_expr = KBChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(KBChunk, distance_expr.label("distance"))
        .where(KBChunk.embedding.is_not(None))
    )
    if normalized_source_type:
        stmt = stmt.where(KBChunk.source_type == normalized_source_type)
    if normalized_keys:
        stmt = stmt.where(KBChunk.jira_key.in_(normalized_keys))
    stmt = stmt.order_by(distance_expr.asc(), KBChunk.updated_at.desc()).limit(limit)
    rows = db.execute(stmt).all()

    return [_match_to_result(chunk, distance=float(distance) if distance is not None else None) for chunk, distance in rows]


def search_kb_issues(db: Session, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search issue-level KB chunks (source_type=jira_issue)."""
    return search_kb(db, query, top_k=top_k, source_type="jira_issue")


def list_comments_for_jira_keys(
    db: Session,
    jira_keys: list[str],
    *,
    limit_per_issue: int = 4,
) -> list[dict[str, Any]]:
    """List recent comment chunks for the provided Jira keys."""
    normalized_keys = [str(key or "").strip() for key in jira_keys if str(key or "").strip()]
    if not normalized_keys:
        return []

    per_issue_limit = max(1, min(int(limit_per_issue), 20))
    try:
        rows = db.execute(
            select(KBChunk)
            .where(
                KBChunk.source_type == "jira_comment",
                KBChunk.jira_key.in_(normalized_keys),
            )
            .order_by(KBChunk.updated_at.desc(), KBChunk.created_at.desc(), KBChunk.id.desc())
        ).scalars().all()
    except Exception:
        return []

    counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for chunk in rows:
        jira_key = str(chunk.jira_key or "").strip()
        if not jira_key:
            continue
        current = counts.get(jira_key, 0)
        if current >= per_issue_limit:
            continue
        counts[jira_key] = current + 1
        selected.append(_match_to_result(chunk))
    return selected
