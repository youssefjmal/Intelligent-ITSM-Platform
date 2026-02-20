"""Shared mutable state for Jira KB caches."""

from __future__ import annotations

import datetime as dt
from threading import Lock

_snapshot_lock = Lock()
_snapshot_expires_at: dt.datetime | None = None
_snapshot_rows: list[dict[str, str]] = []
_kb_chunks_ready: bool | None = None
_kb_chunks_checked_at: dt.datetime | None = None
_embedding_cache_lock = Lock()
_inmemory_embedding_cache: dict[str, list[float]] = {}
