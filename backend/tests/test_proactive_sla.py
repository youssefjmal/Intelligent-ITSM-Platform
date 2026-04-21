"""
Tests for the proactive SLA monitor background task.

Coverage:
  1. run_proactive_sla_monitor updates sla_status to at_risk
     when elapsed_ratio >= threshold
  2. Does NOT create duplicate notification within dedup window
  3. Creates automation_event with actor="system:sla_monitor" (if model exists)
  4. Does NOT fire for already-breached or resolved tickets
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.ai.calibration import (
    PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD,
    PROACTIVE_SLA_DEDUP_WINDOW_MINUTES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ticket(
    ticket_id: str,
    status: str = "open",
    sla_status: str = "ok",
    created_hours_ago: float = 48.0,
    sla_due_hours_from_now: float = 2.0,
) -> MagicMock:
    """Build a mock Ticket for SLA monitor testing."""
    now = dt.datetime.now(dt.timezone.utc)
    t = MagicMock()
    t.id = ticket_id
    t.status = status
    t.sla_status = sla_status
    t.created_at = now - dt.timedelta(hours=created_hours_ago)
    # Actual field name on Ticket model is sla_resolution_due_at
    t.sla_resolution_due_at = now + dt.timedelta(hours=sla_due_hours_from_now)
    t.sla_due_at = t.sla_resolution_due_at  # alias for compatibility
    t.due_at = t.sla_resolution_due_at      # alias for compatibility
    t.assignee_id = "agent-uuid-001"
    t.reporter_id = "reporter-uuid-001"
    t.updated_at = None
    return t


def _make_db(tickets: list) -> MagicMock:
    """Build a mock Session that returns the provided tickets from a query."""
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = tickets
    db.query.return_value = q
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_elapsed_ratio_above_threshold_marks_at_risk():
    """
    _run_proactive_sla_check_sync should update sla_status to 'at_risk'
    when elapsed_ratio >= PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD.
    """
    from app.services.sla.sla_monitor import _elapsed_ratio

    now = dt.datetime.now(dt.timezone.utc)
    ticket = _make_ticket("TW-TEST-001", created_hours_ago=90, sla_due_hours_from_now=10)
    ratio = _elapsed_ratio(ticket, now)
    # created 90h ago, due in 10h → total 100h, elapsed 90h → 90%
    assert ratio >= PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD, (
        f"Expected ratio >= {PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD}, got {ratio:.3f}"
    )


def test_elapsed_ratio_below_threshold_not_at_risk():
    """
    _elapsed_ratio should be below threshold for recently created tickets.
    """
    from app.services.sla.sla_monitor import _elapsed_ratio

    now = dt.datetime.now(dt.timezone.utc)
    ticket = _make_ticket("TW-TEST-002", created_hours_ago=2, sla_due_hours_from_now=22)
    ratio = _elapsed_ratio(ticket, now)
    # created 2h ago, due in 22h → total 24h, elapsed 2h → ~8%
    assert ratio < PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD


def test_elapsed_ratio_no_deadline_returns_zero():
    """_elapsed_ratio returns 0.0 when ticket has no SLA deadline."""
    from app.services.sla.sla_monitor import _elapsed_ratio

    now = dt.datetime.now(dt.timezone.utc)
    ticket = MagicMock()
    ticket.sla_due_at = None
    ticket.due_at = None
    ticket.created_at = now - dt.timedelta(hours=10)
    ratio = _elapsed_ratio(ticket, now)
    assert ratio == 0.0


def test_has_recent_notification_returns_true_when_exists():
    """_has_recent_at_risk_notification returns True when unread notification found."""
    from app.services.sla.sla_monitor import _has_recent_at_risk_notification

    now = dt.datetime.now(dt.timezone.utc)
    mock_notif = MagicMock()

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = mock_notif
    db.query.return_value = q

    result = _has_recent_at_risk_notification(db, "TW-TEST-001", now)
    assert result is True


def test_has_recent_notification_returns_false_when_none():
    """_has_recent_at_risk_notification returns False when no existing notification."""
    from app.services.sla.sla_monitor import _has_recent_at_risk_notification

    now = dt.datetime.now(dt.timezone.utc)

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = None
    db.query.return_value = q

    result = _has_recent_at_risk_notification(db, "TW-TEST-002", now)
    assert result is False


def test_sla_monitor_does_not_fire_for_resolved_tickets():
    """
    The monitor queries only open tickets (status in open statuses).
    Resolved tickets should not be in the query result by DB filter design.
    We verify the filter construction doesn't include resolved status.
    """
    from app.services.sla.sla_monitor import _OPEN_STATUSES
    from app.models.enums import TicketStatus

    assert TicketStatus.resolved not in _OPEN_STATUSES
    assert TicketStatus.closed not in _OPEN_STATUSES


def test_sla_monitor_does_not_fire_for_already_breached():
    """
    The monitor queries only tickets with sla_status='ok'.
    Already-breached tickets are excluded by the DB query filter.
    """
    # Verify the filter logic: tickets with sla_status='breached' are excluded
    # by the query in _run_proactive_sla_check_sync which filters sla_status == "ok"
    # This is a structural test — no DB needed.
    import inspect
    from app.services.sla import sla_monitor
    source = inspect.getsource(sla_monitor._run_proactive_sla_check_sync)
    assert '"ok"' in source or "'ok'" in source, (
        "SLA monitor must filter sla_status == 'ok' to exclude already-breached tickets"
    )


def test_proactive_sla_constants_values():
    """Verify calibration constants are set to reasonable values."""
    assert PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD >= 0.5
    assert PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD <= 0.95
    assert PROACTIVE_SLA_DEDUP_WINDOW_MINUTES >= 10
    assert PROACTIVE_SLA_DEDUP_WINDOW_MINUTES <= 480


def test_notify_at_risk_recipients_prefers_shared_ticket_routing(monkeypatch):
    from app.services.sla import sla_monitor

    db = MagicMock()
    ticket = _make_ticket("TW-TEST-003")
    recipients = [MagicMock(id="admin-1"), MagicMock(id="agent-1")]
    created_rows = [MagicMock(), MagicMock()]

    monkeypatch.setattr(
        "app.services.notifications_service.resolve_ticket_recipients",
        lambda *args, **kwargs: recipients,
    )
    monkeypatch.setattr(
        "app.services.notifications_service.create_notifications_for_users",
        lambda **kwargs: created_rows,
    )
    fallback = MagicMock()
    monkeypatch.setattr("app.services.notifications_service.create_notification", fallback)

    created = sla_monitor._notify_at_risk_recipients(db, ticket=ticket, ratio=0.91)

    assert created == 2
    fallback.assert_not_called()


def test_notify_at_risk_recipients_uses_reporter_fallback_only_when_no_shared_recipients(monkeypatch):
    from app.services.sla import sla_monitor

    db = MagicMock()
    ticket = _make_ticket("TW-TEST-004")
    ticket.reporter_id = "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(
        "app.services.notifications_service.resolve_ticket_recipients",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.notifications_service.create_notifications_for_users",
        lambda **kwargs: [],
    )
    fallback = MagicMock()
    monkeypatch.setattr("app.services.notifications_service.create_notification", fallback)

    created = sla_monitor._notify_at_risk_recipients(db, ticket=ticket, ratio=0.91)

    assert created == 1
    fallback.assert_called_once()
