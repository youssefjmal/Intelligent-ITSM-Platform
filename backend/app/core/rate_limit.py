"""In-memory rate limiting dependency."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque

from fastapi import Request, Response

from app.core.config import settings
from app.core.exceptions import RateLimitExceeded


class SlidingWindowLimiter:
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


_limiter = SlidingWindowLimiter()


def _client_key(request: Request, scope: str) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"{scope}:{ip}"


def _scope_limit(scope: str) -> int:
    if scope == "auth":
        return settings.RATE_LIMIT_AUTH_MAX_REQUESTS
    if scope == "ai":
        return settings.RATE_LIMIT_AI_MAX_REQUESTS
    return settings.RATE_LIMIT_MAX_REQUESTS


def rate_limit(scope: str = "default"):
    def _dependency(request: Request, response: Response) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = _scope_limit(scope)
        key = _client_key(request, scope)
        ok, remaining, retry_after = _limiter.hit(
            key,
            limit=limit,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(remaining, 0))
        response.headers["X-RateLimit-Window"] = str(settings.RATE_LIMIT_WINDOW_SECONDS)
        if not ok:
            raise RateLimitExceeded(
                retry_after=retry_after,
                limit=limit,
                window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
            )

    return _dependency
