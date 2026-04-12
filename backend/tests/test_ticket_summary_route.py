from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.routers import tickets as tickets_router
from app.services.ai.summarization import SummaryResult


def _ticket(ticket_id: str = "TW-MOCK-001") -> SimpleNamespace:
    now = dt.datetime(2026, 4, 9, 10, 0, tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        title="VPN clients disconnect after overnight certificate rotation",
        description="Finance users lose VPN connectivity after the scheduled certificate rotation window.",
        category=TicketCategory.network,
        priority=TicketPriority.high,
        status=TicketStatus.open,
        assignee="Nadia Boucher",
        reporter="finance@corp.local",
        ai_summary="Cached summary",
        summary_generated_at=now,
    )


def _summary_result() -> SummaryResult:
    return SummaryResult(
        summary="Finance users are impacted by a VPN certificate rollover issue.",
        similar_ticket_count=2,
        used_ticket_ids=["TW-MOCK-010", "TW-MOCK-011"],
        generated_at=dt.datetime(2026, 4, 9, 10, 5, tzinfo=dt.timezone.utc),
        is_cached=False,
        language="en",
    )


def test_get_ticket_summary_uses_authorized_ticket_and_preserves_response(monkeypatch) -> None:
    ticket = _ticket()
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)
    db = object()
    captured: dict[str, object] = {}

    async def fake_generate_ticket_summary(ticket_dict, **kwargs):
        captured["ticket_dict"] = ticket_dict
        captured["kwargs"] = kwargs
        return _summary_result()

    monkeypatch.setattr(tickets_router, "get_ticket_for_user", lambda db, ticket_id, user: ticket)
    monkeypatch.setattr(
        "app.services.ai.summarization.generate_ticket_summary",
        fake_generate_ticket_summary,
    )

    response = asyncio.run(
        tickets_router.get_ticket_summary(
            ticket_id=ticket.id,
            force_regenerate=True,
            language="en",
            db=db,
            current_user=current_user,
        )
    )

    assert captured["ticket_dict"] == {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "category": ticket.category.value,
        "priority": ticket.priority.value,
        "status": ticket.status.value,
        "assignee": ticket.assignee,
        "reporter": ticket.reporter,
        "ai_summary": ticket.ai_summary,
        "summary_generated_at": ticket.summary_generated_at,
    }
    assert captured["kwargs"] == {"db": db, "force_regenerate": True, "language": "en"}
    assert response == {
        "summary": "Finance users are impacted by a VPN certificate rollover issue.",
        "similar_ticket_count": 2,
        "used_ticket_ids": ["TW-MOCK-010", "TW-MOCK-011"],
        "generated_at": "2026-04-09T10:05:00+00:00",
        "is_cached": False,
        "language": "en",
    }


def test_get_ticket_summary_denies_hidden_ticket_with_not_found(monkeypatch) -> None:
    current_user = SimpleNamespace(id="viewer-1", role=UserRole.viewer)

    monkeypatch.setattr(tickets_router, "get_ticket_for_user", lambda db, ticket_id, user: None)

    with pytest.raises(NotFoundError) as exc_info:
        asyncio.run(
            tickets_router.get_ticket_summary(
                ticket_id="TW-HIDDEN-999",
                db=object(),
                current_user=current_user,
            )
        )

    exc = exc_info.value
    assert exc.message == "ticket_not_found"
    assert exc.details == {"ticket_id": "TW-HIDDEN-999"}
    assert exc.status_code == 404


def test_get_ticket_summary_uses_same_not_found_shape_for_missing_and_unauthorized(monkeypatch) -> None:
    current_user = SimpleNamespace(id="viewer-1", role=UserRole.viewer)

    monkeypatch.setattr(tickets_router, "get_ticket_for_user", lambda db, ticket_id, user: None)

    hidden_exc = None
    missing_exc = None

    for ticket_id in ("TW-HIDDEN-999", "TW-MISSING-404"):
        with pytest.raises(NotFoundError) as exc_info:
            asyncio.run(
                tickets_router.get_ticket_summary(
                    ticket_id=ticket_id,
                    db=object(),
                    current_user=current_user,
                )
            )
        if ticket_id == "TW-HIDDEN-999":
            hidden_exc = exc_info.value
        else:
            missing_exc = exc_info.value

    assert hidden_exc is not None
    assert missing_exc is not None
    assert hidden_exc.message == missing_exc.message == "ticket_not_found"
    assert hidden_exc.status_code == missing_exc.status_code == 404
