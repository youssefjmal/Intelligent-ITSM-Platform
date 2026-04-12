from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.services.ai.chat_payloads import build_similar_tickets_payload


def _ticket(ticket_id: str, title: str, *, category=TicketCategory.application, ticket_type=TicketType.incident):
    now = dt.datetime(2026, 4, 9, 12, 0, tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        title=title,
        description=f"{title} description",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=ticket_type,
        category=category,
        assignee="Agent",
        reporter="Reporter",
        created_at=now,
        updated_at=now,
    )


def test_build_similar_tickets_payload_uses_same_visible_filters_as_ticket_detail() -> None:
    source_ticket = _ticket("TW-MOCK-013", "Finance dashboard export fails after overnight patch")
    visible_match = _ticket("TW-MOCK-025", "Payroll export CSV writes broken date values")
    secondary_match = _ticket("TW-MOCK-032", "Prepare audit evidence export package")

    resolver_output = SimpleNamespace(
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

    payload = build_similar_tickets_payload(
        source_ticket_id=source_ticket.id,
        source_ticket=source_ticket,
        visible_tickets=[source_ticket, visible_match, secondary_match],
        resolver_output=resolver_output,
        lang="en",
    )

    assert payload.type == "similar_tickets"
    assert [row.ticket_id for row in payload.matches] == [secondary_match.id, visible_match.id]
