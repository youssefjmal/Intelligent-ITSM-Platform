from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType, UserRole
from app.routers import tickets as tickets_router


def _ticket(ticket_id: str, title: str) -> SimpleNamespace:
    now = dt.datetime(2026, 3, 23, 10, 0, tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        title=title,
        description=f"{title} description",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.incident,
        category=TicketCategory.application,
        assignee="Amina Rafi",
        reporter="Yassir Hamdi",
        created_at=now,
        updated_at=now,
    )


def test_get_similar_tickets_uses_shared_resolver_retrieval(monkeypatch) -> None:
    source_ticket = _ticket("TW-MOCK-013", "Finance dashboard export fails after overnight patch")
    visible_match = _ticket("TW-MOCK-025", "Payroll export CSV writes broken date values")
    secondary_match = _ticket("TW-MOCK-032", "Prepare audit evidence export package")
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)
    captured: dict[str, object] = {}

    def fake_resolve_ticket_advice(db, ticket, **kwargs):
        captured["ticket_id"] = ticket.id
        captured["visible_ids"] = [row.id for row in kwargs.get("visible_tickets") or []]
        captured["top_k"] = kwargs.get("top_k")
        return SimpleNamespace(
            retrieval={
                "similar_tickets": [
                    {"id": secondary_match.id, "similarity_score": 0.79},
                    {"id": "TW-HIDDEN-999", "similarity_score": 0.95},
                    {"id": source_ticket.id, "similarity_score": 0.93},
                    {"id": visible_match.id, "similarity_score": 0.72},
                    {"id": "TW-MOCK-LOW", "similarity_score": 0.18},
                ]
            }
        )

    monkeypatch.setattr(tickets_router, "get_ticket_for_user", lambda db, ticket_id, user: source_ticket)
    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda db, user: [source_ticket, visible_match, secondary_match])
    monkeypatch.setattr(tickets_router, "resolve_ticket_advice", fake_resolve_ticket_advice)

    response = tickets_router.get_similar_tickets(
        ticket_id=source_ticket.id,
        limit=2,
        min_score=0.3,
        db=object(),
        current_user=current_user,
    )

    assert captured == {
        "ticket_id": source_ticket.id,
        "visible_ids": [source_ticket.id, visible_match.id, secondary_match.id],
        "top_k": 5,
    }
    assert response.ticket_id == source_ticket.id
    assert [item.id for item in response.matches] == [secondary_match.id, visible_match.id]
    assert [item.similarity_score for item in response.matches] == [0.79, 0.72]


def test_get_similar_tickets_uses_cross_check_for_contextual_service_request_detection(monkeypatch) -> None:
    now = dt.datetime(2026, 3, 23, 10, 0, tzinfo=dt.timezone.utc)
    source_ticket = SimpleNamespace(
        id="TW-MOCK-012",
        title="Create distribution list for the ops war room",
        description="Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.incident,
        category=TicketCategory.email,
        assignee="Nadia Boucher",
        reporter="Finance Team",
        created_at=now,
        updated_at=now,
    )
    service_request_match = SimpleNamespace(
        id="TW-MOCK-022",
        title="Create release-notification distribution list for the ops bridge",
        description="Create a new distribution list for release bridge updates and add the approved engineering roster.",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        assignee="Mohamed Chaari",
        reporter="Support Desk",
        created_at=now,
        updated_at=now,
    )
    incident_match = _ticket("TW-MOCK-001", "VPN login loops after MFA for finance users")
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)

    def fake_resolve_ticket_advice(db, ticket, **kwargs):
        return SimpleNamespace(
            retrieval={
                "similar_tickets": [
                    {"id": incident_match.id, "similarity_score": 0.88},
                    {"id": service_request_match.id, "similarity_score": 0.84},
                ]
            }
        )

    monkeypatch.setattr(tickets_router, "get_ticket_for_user", lambda db, ticket_id, user: source_ticket)
    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda db, user: [source_ticket, service_request_match, incident_match])
    monkeypatch.setattr(tickets_router, "resolve_ticket_advice", fake_resolve_ticket_advice)

    response = tickets_router.get_similar_tickets(
        ticket_id=source_ticket.id,
        limit=5,
        min_score=0.2,
        db=object(),
        current_user=current_user,
    )

    assert [item.id for item in response.matches] == [service_request_match.id]
