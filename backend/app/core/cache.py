"""Thin Redis wrapper with graceful fallback for the ITSM platform.

Every public function silently returns None / False when Redis is unavailable
so callers never need try/except around cache calls.

Key format:  itsm:{resource}:{user_id}[:{params_hash12}]
Values:      UTF-8 JSON  (json.dumps with default=str handles datetime/UUID/enum)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

try:
    import redis as _redis_lib
except ModuleNotFoundError:  # pragma: no cover - depends on local optional dependency
    _redis_lib = None

from app.core.config import settings
from app.core.metrics import cache_hits_total, cache_misses_total

logger = logging.getLogger(__name__)

_client: Any | None = None
_client_initialised = False  # True once we have attempted a connection


def _get_client() -> Any | None:
    global _client, _client_initialised
    if _client_initialised:
        return _client
    _client_initialised = True
    if not settings.CACHE_ENABLED:
        return None
    if _redis_lib is None:
        logger.warning("Redis client library not installed; caching disabled.")
        return None
    try:
        c = _redis_lib.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        c.ping()
        _client = c
        logger.info("Redis cache connected: %s", settings.REDIS_URL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — caching disabled. Reason: %s", exc)
    return _client


def make_key(resource: str, user_id: str | None, params: dict[str, Any] | None = None) -> str:
    """Build a canonical cache key.

    Args:
        resource: short label e.g. "stats", "insights", "embedding".
        user_id:  str(user.id) or None for global keys.
        params:   extra query parameters that distinguish variants.
                  Sorted before hashing so key is stable regardless of dict order.
    """
    uid = str(user_id or "global")
    if params:
        stable = json.dumps(params, sort_keys=True, default=str)
        phash = hashlib.sha256(stable.encode()).hexdigest()[:12]
        return f"itsm:{resource}:{uid}:{phash}"
    return f"itsm:{resource}:{uid}"


def get(key: str) -> Any | None:
    """Return deserialized value or None on miss / Redis unavailable."""
    c = _get_client()
    if c is None:
        return None
    try:
        raw = c.get(key)
        _resource = key.split(":")[1] if ":" in key else "unknown"
        (cache_hits_total if raw is not None else cache_misses_total).labels(resource=_resource).inc()
        return json.loads(raw) if raw is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache.get failed key=%s: %s", key, exc)
        return None


def set(key: str, value: Any, ttl: int) -> bool:
    """Serialize value to JSON and store with TTL seconds. Returns True on success."""
    c = _get_client()
    if c is None:
        return False
    try:
        c.setex(key, ttl, json.dumps(value, default=str))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache.set failed key=%s: %s", key, exc)
        return False


def delete(key: str) -> bool:
    """Delete a single key. Returns True if the key existed."""
    c = _get_client()
    if c is None:
        return False
    try:
        return bool(c.delete(key))
    except Exception:  # noqa: BLE001
        return False


def delete_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern using SCAN (non-blocking).

    Returns the count of deleted keys.
    """
    c = _get_client()
    if c is None:
        return 0
    deleted = 0
    try:
        for key in c.scan_iter(match=pattern, count=100):
            c.delete(key)
            deleted += 1
    except Exception:  # noqa: BLE001
        pass
    return deleted


def close() -> None:
    """Close the Redis connection pool. Called from app lifespan shutdown."""
    global _client, _client_initialised
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
    _client = None
    _client_initialised = False
