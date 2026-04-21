from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType, UserRole
from app.routers import tickets as tickets_router


def _ticket(ticket_id: str, *, description: str) -> SimpleNamespace:
    now = dt.datetime(2026, 4, 13, 12, 0, tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        problem_id=None,
        title="Synthetic ticket",
        description=description,
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.incident,
        category=TicketCategory.application,
        assignee="Ops Team",
        reporter="Jira",
        auto_assignment_applied=False,
        auto_priority_applied=False,
        assignment_model_version="legacy",
        priority_model_version="jira-native",
        predicted_priority=None,
        predicted_ticket_type=None,
        predicted_category=None,
        assignment_change_count=0,
        first_action_at=None,
        resolved_at=None,
        due_at=None,
        sla_status=None,
        sla_remaining_minutes=None,
        sla_first_response_due_at=None,
        sla_resolution_due_at=None,
        sla_first_response_breached=False,
        sla_resolution_breached=False,
        sla_last_synced_at=None,
        created_at=now,
        updated_at=now,
        resolution=None,
        change_risk=None,
        change_scheduled_at=None,
        change_approved=None,
        change_approved_by=None,
        change_approved_at=None,
        tags=[],
        comments=[],
        jira_key=ticket_id,
    )


def test_get_all_tickets_sanitizes_short_descriptions(monkeypatch) -> None:
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)
    invalid_ticket = _ticket("TEAMWILL-86", description="test")

    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda db, user: [invalid_ticket])

    result = tickets_router.get_all_tickets(sla_status=None, db=object(), current_user=current_user)

    assert len(result) == 1
    assert result[0].id == "TEAMWILL-86"
    assert len(result[0].description) >= 5
    assert result[0].description == "Synthetic ticket"


def test_get_all_tickets_returns_mixed_valid_and_sanitized_rows(monkeypatch) -> None:
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)
    valid_ticket = _ticket("TEAMWILL-90", description="Valid description")
    invalid_ticket = _ticket("TEAMWILL-86", description="test")

    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda db, user: [valid_ticket, invalid_ticket])

    result = tickets_router.get_all_tickets(sla_status=None, db=object(), current_user=current_user)

    assert [ticket.id for ticket in result] == ["TEAMWILL-90", "TEAMWILL-86"]
    assert result[0].description == "Valid description"
    assert result[1].description == "Synthetic ticket"


def test_get_all_tickets_sanitizes_invalid_predicted_enums(monkeypatch) -> None:
    current_user = SimpleNamespace(id="agent-1", role=UserRole.agent)
    invalid_ticket = _ticket("TEAMWILL-91", description="Valid description")
    invalid_ticket.predicted_priority = "urgent-impossible"
    invalid_ticket.predicted_ticket_type = "mystery-type"
    invalid_ticket.predicted_category = "unknown-bucket"

    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda db, user: [invalid_ticket])

    result = tickets_router.get_all_tickets(sla_status=None, db=object(), current_user=current_user)

    assert len(result) == 1
    assert result[0].predicted_priority is None
    assert result[0].predicted_ticket_type is None
    assert result[0].predicted_category is None
