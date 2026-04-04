from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services import notifications_service as notifications


class _FakeDB:
    def __init__(self) -> None:
        self.added = []
        self.flushed = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed += 1


def _pref(**overrides):  # noqa: ANN001
    defaults = {
        "email_enabled": True,
        "email_min_severity": "critical",
        "immediate_email_min_severity": "high",
        "digest_enabled": True,
        "digest_frequency": "hourly",
        "quiet_hours_enabled": False,
        "quiet_hours_start": None,
        "quiet_hours_end": None,
        "critical_bypass_quiet_hours": True,
        "ticket_assignment_enabled": True,
        "ticket_comment_enabled": True,
        "sla_notifications_enabled": True,
        "problem_notifications_enabled": True,
        "ai_notifications_enabled": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _user(**overrides):  # noqa: ANN001
    defaults = {
        "id": uuid4(),
        "email": "agent@example.com",
        "name": "Agent One",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _notification(**overrides):  # noqa: ANN001
    defaults = {
        "id": uuid4(),
        "event_type": notifications.EVENT_TICKET_ASSIGNED,
        "title": "Ticket assigned: TW-1001",
        "body": "You are now responsible for the ticket.",
        "severity": "warning",
        "link": "/tickets/TW-1001",
        "source": "ticket",
        "metadata_json": {"ticket_id": "TW-1001", "ticket_title": "VPN login fails"},
        "action_payload": {"ticket_id": "TW-1001"},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_ai_recommendation_dedupe_key_changes_when_action_changes() -> None:
    base = notifications._build_dedupe_key(
        event_type=notifications.EVENT_AI_RECOMMENDATION_READY,
        link="/tickets/TW-42",
        severity="info",
        metadata_json={
            "ticket_id": "TW-42",
            "recommended_action": "Restart the VPN gateway service.",
            "confidence_band": "medium",
            "tentative": False,
            "recommendation_mode": "evidence_grounded",
        },
        action_payload=None,
        body="Resolver updated the action.",
    )
    changed = notifications._build_dedupe_key(
        event_type=notifications.EVENT_AI_RECOMMENDATION_READY,
        link="/tickets/TW-42",
        severity="info",
        metadata_json={
            "ticket_id": "TW-42",
            "recommended_action": "Rebuild the forwarding rule with the current connector identity.",
            "confidence_band": "medium",
            "tentative": False,
            "recommendation_mode": "evidence_grounded",
        },
        action_payload=None,
        body="Resolver updated the action.",
    )

    assert base != changed


def test_route_notification_delivery_prefers_n8n_for_critical_sla_breach(monkeypatch) -> None:
    monkeypatch.setattr(notifications, "get_or_create_notification_preference", lambda *_args, **_kwargs: _pref())
    route, reason = notifications.route_notification_delivery(
        db=object(),
        notification=_notification(
            event_type=notifications.EVENT_SLA_BREACHED,
            severity="critical",
            source="sla",
        ),
        user=_user(),
    )

    assert route == notifications.ROUTE_N8N_WORKFLOW
    assert reason == "workflow_route"


def test_route_notification_delivery_queues_digest_for_medium_assignment(monkeypatch) -> None:
    monkeypatch.setattr(
        notifications,
        "get_or_create_notification_preference",
        lambda *_args, **_kwargs: _pref(immediate_email_min_severity="high", digest_enabled=True),
    )
    route, reason = notifications.route_notification_delivery(
        db=object(),
        notification=_notification(
            event_type=notifications.EVENT_TICKET_ASSIGNED,
            severity="warning",
            source="ticket",
        ),
        user=_user(),
    )

    assert route == notifications.ROUTE_DIGEST_QUEUE
    assert reason == "digest_queue"


def test_dispatch_notification_delivery_falls_back_to_email_when_n8n_fails(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        notifications,
        "route_notification_delivery",
        lambda *_args, **_kwargs: (notifications.ROUTE_N8N_WORKFLOW, "workflow_route"),
    )
    monkeypatch.setattr(notifications, "_dispatch_n8n_notification", lambda **_kwargs: (False, "n8n_down"))
    monkeypatch.setattr(notifications, "log_delivery_event", lambda *_args, **_kwargs: None)

    def _fake_email(*_args, **kwargs):  # noqa: ANN001
        events.append("email_fallback")
        assert kwargs["force"] is True
        return True, "email_sent"

    monkeypatch.setattr(notifications, "dispatch_email_for_notification", _fake_email)

    ok, reason = notifications.dispatch_notification_delivery(
        db=object(),
        notification=_notification(event_type=notifications.EVENT_SLA_BREACHED, severity="critical", source="sla"),
        user=_user(),
    )

    assert ok is True
    assert reason == "email_sent"
    assert events == ["email_fallback"]


def test_create_notifications_for_users_suppresses_duplicates(monkeypatch) -> None:
    db = _FakeDB()
    users = [_user(email="one@example.com"), _user(email="two@example.com")]
    dispatched: list[str] = []
    suppressed: list[str] = []

    monkeypatch.setattr(notifications, "_filter_recipients_for_event", lambda *_args, **_kwargs: users)
    monkeypatch.setattr(
        notifications,
        "_recent_unread_duplicate_exists",
        lambda *_args, user_id, **_kwargs: uuid4() if user_id == users[0].id else None,
    )
    monkeypatch.setattr(
        notifications,
        "dispatch_notification_delivery",
        lambda *_args, notification, user, **_kwargs: dispatched.append(str(user.email)) or (True, "ok"),
    )
    monkeypatch.setattr(
        notifications,
        "log_delivery_event",
        lambda *_args, recipients=None, **_kwargs: suppressed.append(",".join(recipients or [])) or None,
    )

    created = notifications.create_notifications_for_users(
        db,
        users=users,
        title="Ticket assigned: TW-1001",
        body="You are now responsible for the ticket.",
        severity="warning",
        link="/tickets/TW-1001",
        source="ticket",
        cooldown_minutes=20,
        metadata_json={"ticket_id": "TW-1001"},
        action_type="view",
        action_payload={"ticket_id": "TW-1001"},
        event_type=notifications.EVENT_TICKET_ASSIGNED,
    )

    assert len(created) == 1
    assert dispatched == ["two@example.com"]
    assert suppressed == ["one@example.com"]


def test_notify_ticket_assignment_change_emits_reassignment_for_new_and_previous_assignee(monkeypatch) -> None:
    new_assignee = _user(name="New Owner", email="new.owner@example.com")
    previous_assignee = _user(name="Old Owner", email="old.owner@example.com")
    captured: list[dict] = []

    def _find_user(_db, identity: str | None):  # noqa: ANN001
        if identity == "New Owner":
            return new_assignee
        if identity == "Old Owner":
            return previous_assignee
        return None

    def _capture(_db, **kwargs):  # noqa: ANN001
        captured.append(kwargs)
        return []

    monkeypatch.setattr(notifications, "_find_user_by_identity", _find_user)
    monkeypatch.setattr(notifications, "create_notifications_for_users", _capture)

    notifications.notify_ticket_assignment_change(
        db=object(),
        ticket=SimpleNamespace(id="TW-1001", title="VPN login fails", assignee="New Owner", priority="high"),
        previous_assignee="Old Owner",
        actor="Dispatcher Bot",
    )

    assert len(captured) == 2
    assert captured[0]["event_type"] == notifications.EVENT_TICKET_REASSIGNED
    assert captured[0]["users"] == [new_assignee]
    assert captured[1]["users"] == [previous_assignee]
