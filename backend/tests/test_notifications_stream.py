from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.routers import notifications as notifications_router


def test_count_unread_notifications_for_stream_uses_fresh_session_per_poll(monkeypatch) -> None:
    sessions: list[object] = []
    closed: list[object] = []

    class _Session:
        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            closed.append(self)

    monkeypatch.setattr(notifications_router, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(
        notifications_router,
        "count_unread_notifications",
        lambda db, *, user_id: 7 if user_id == "user-1" else 0,
    )

    first = notifications_router._count_unread_notifications_for_stream("user-1")
    second = notifications_router._count_unread_notifications_for_stream("user-1")

    assert first == 7
    assert second == 7
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert closed == sessions


def test_stream_unread_count_events_yields_multiple_sse_frames() -> None:
    counts = iter([3, 4])
    sleep_calls = 0

    async def _fake_sleep(_seconds: int) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError()

    async def _consume() -> list[str]:
        original_sleep = notifications_router.asyncio.sleep
        original_reader = notifications_router._count_unread_notifications_for_stream
        notifications_router.asyncio.sleep = _fake_sleep
        notifications_router._count_unread_notifications_for_stream = lambda _user_id: next(counts)
        try:
            stream = notifications_router._stream_unread_count_events("user-1")
            first = await anext(stream)
            second = await anext(stream)
            await stream.aclose()
            return [first, second]
        finally:
            notifications_router.asyncio.sleep = original_sleep
            notifications_router._count_unread_notifications_for_stream = original_reader

    frames = asyncio.run(_consume())

    assert frames == [
        'data: {"unread_count": 3}\n\n',
        'data: {"unread_count": 4}\n\n',
    ]


def test_stream_unread_count_route_returns_streaming_response() -> None:
    response = asyncio.run(
        notifications_router.stream_unread_count(
            current_user=SimpleNamespace(id="user-1"),
        )
    )

    assert response.media_type == "text/event-stream"
