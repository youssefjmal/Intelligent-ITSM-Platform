"""Rate limiting — Redis-backed sliding window with in-memory fallback.

Architecture
------------
Primary:  Redis sorted-set sliding window (shared across all Uvicorn workers).
          Each key is a sorted set of request timestamps.
          ZADD + ZREMRANGEBYSCORE + ZCARD executed in a single pipeline (atomic).

Fallback: In-memory deque (original implementation) — used automatically when
          Redis is unavailable.  Logs a one-time warning so ops know degraded
          mode is active.

IP resolution (GAP 2 fix)
--------------------------
By default uses request.client.host (the real TCP peer).
Only reads X-Forwarded-For when TRUST_PROXY=true in settings, and when it does,
it takes the last TRUSTED_PROXY_DEPTH entry from the right (the part the proxy
itself wrote) rather than the leftmost entry (which the attacker controls).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Deque

from fastapi import FastAPI, Request, Response

from app.core.config import settings
from app.core.exceptions import RateLimitExceeded
from app.core.metrics import rate_limit_exceeded_total

logger = logging.getLogger(__name__)

# ── in-memory fallback ───────────────────────────────────────────────────────

class _InMemoryLimiter:
    def __init__(self) -> None:
        self._store: dict[str, Deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        if limit <= 0:
            return True, limit, 0
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            queue = self._store.get(key)
            if queue is None:
                queue = deque()
                self._store[key] = queue
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= limit:
                retry_after = max(int(queue[0] + window_seconds - now), 1)
                return False, 0, retry_after
            queue.append(now)
            remaining = max(limit - len(queue), 0)
            if not queue:
                self._store.pop(key, None)
            return True, remaining, 0


_in_memory = _InMemoryLimiter()
_redis_warning_emitted = False


# ── Redis sliding-window ─────────────────────────────────────────────────────

def _redis_hit(key: str, *, limit: int, window_seconds: int) -> tuple[bool, int, int] | None:
    """Attempt a Redis sorted-set sliding window.

    Returns (allowed, remaining, retry_after) on success, or None if Redis is
    unavailable so the caller can fall through to the in-memory limiter.
    """
    global _redis_warning_emitted
    from app.core.cache import _get_client  # lazy import — avoids circular at module load
    client = _get_client()
    if client is None:
        if not _redis_warning_emitted:
            logger.warning(
                "Rate limiter: Redis unavailable — falling back to per-process in-memory limiter. "
                "Multi-worker deployments will see relaxed limits until Redis reconnects."
            )
            _redis_warning_emitted = True
        return None

    now = time.time()
    cutoff = now - window_seconds
    redis_key = f"rl:{key}"

    try:
        pipe = client.pipeline()
        # Remove timestamps older than the window
        pipe.zremrangebyscore(redis_key, "-inf", cutoff)
        # Count remaining requests in window
        pipe.zcard(redis_key)
        # Add this request (score = timestamp, member = unique float for dedup)
        pipe.zadd(redis_key, {str(now): now})
        # Set expiry so orphaned keys clean themselves up
        pipe.expire(redis_key, window_seconds + 5)
        results = pipe.execute()

        count_before_add = int(results[1])
        if count_before_add >= limit:
            # Already over limit — remove the entry we just added
            client.zrem(redis_key, str(now))
            # Estimate retry_after from oldest timestamp in the window
            oldest = client.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(int(oldest[0][1] + window_seconds - now), 1)
            else:
                retry_after = window_seconds
            return False, 0, retry_after

        remaining = max(limit - count_before_add - 1, 0)
        return True, remaining, 0

    except Exception as exc:  # noqa: BLE001
        logger.debug("Rate limiter Redis error (key=%s): %s — using in-memory fallback", key, exc)
        return None


# ── IP extraction (GAP 2) ────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    """Return the real client IP, resistant to X-Forwarded-For spoofing.

    When TRUST_PROXY is false (default): always use the TCP peer address.
    When TRUST_PROXY is true: peel TRUSTED_PROXY_DEPTH hops from the right of
    the X-Forwarded-For list — the rightmost hop is the one the trusted proxy
    appended, not the one the client supplied.
    """
    if not settings.TRUST_PROXY:
        return request.client.host if request.client else "unknown"

    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return request.client.host if request.client else "unknown"

    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if not hops:
        return request.client.host if request.client else "unknown"

    depth = max(1, settings.TRUSTED_PROXY_DEPTH)
    # The rightmost `depth` entries were written by trusted proxies.
    # We want the first untrusted hop, which is at index -(depth+1) from the right,
    # but if depth >= len(hops) we fall back to the leftmost entry.
    idx = max(len(hops) - depth - 1, 0)
    return hops[idx]


def _client_key(request: Request, scope: str) -> str:
    return f"{scope}:{_client_ip(request)}"


# ── scope helper ─────────────────────────────────────────────────────────────

def _scope_limit(scope: str) -> int:
    if scope == "auth":
        return settings.RATE_LIMIT_AUTH_MAX_REQUESTS
    if scope == "ai":
        return settings.RATE_LIMIT_AI_MAX_REQUESTS
    return settings.RATE_LIMIT_MAX_REQUESTS


# ── unified hit — Redis first, in-memory fallback ────────────────────────────

def _hit(key: str, *, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    result = _redis_hit(key, limit=limit, window_seconds=window_seconds)
    if result is not None:
        return result
    return _in_memory.hit(key, limit=limit, window_seconds=window_seconds)


# ── public FastAPI dependency ─────────────────────────────────────────────────

def rate_limit(scope: str = "default"):
    def _dependency(request: Request, response: Response) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = _scope_limit(scope)
        key = _client_key(request, scope)
        ok, remaining, retry_after = _hit(
            key,
            limit=limit,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(remaining, 0))
        response.headers["X-RateLimit-Window"] = str(settings.RATE_LIMIT_WINDOW_SECONDS)
        if not ok:
            rate_limit_exceeded_total.labels(scope=scope).inc()
            raise RateLimitExceeded(
                retry_after=retry_after,
                limit=limit,
                window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
            )

    return _dependency


# ── global middleware ─────────────────────────────────────────────────────────

def install_global_rate_limit_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def global_rate_limit(request: Request, call_next):  # type: ignore[override]
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path or ""
        if (
            path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/openapi.json")
            or path == "/metrics"
        ):
            return await call_next(request)

        scope = "default"
        if path.startswith("/api/auth"):
            scope = "auth"
        elif path.startswith("/api/ai"):
            scope = "ai"

        limit = _scope_limit(scope)
        key = _client_key(request, scope)
        ok, remaining, retry_after = _hit(
            key,
            limit=limit,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
        if not ok:
            rate_limit_exceeded_total.labels(scope=scope).inc()
            raise RateLimitExceeded(
                retry_after=retry_after,
                limit=limit,
                window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(remaining, 0))
        response.headers["X-RateLimit-Window"] = str(settings.RATE_LIMIT_WINDOW_SECONDS)
        return response
