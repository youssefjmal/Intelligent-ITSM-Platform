from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketStatus, UserRole
from app.routers.sla import SLABatchRunRequest, get_ticket_ai_risk_latest, run_sla_batch
from app.services.ai.ai_sla_risk import build_sla_advisory


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None


class _ExecResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _ScalarResult(self._values)


class _NestedTxn:
    def rollback(self):
        return None


class _FakeDBDryRun:
    def __init__(self, ticket):
        self.ticket = ticket
        self.commits = 0

    def execute(self, _query):
        return _ExecResult([self.ticket.id])

    def get(self, _model, _key):
        return self.ticket

    def begin_nested(self):
        return _NestedTxn()

    def refresh(self, _obj):
        return None

    def add(self, _obj):
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        return None


class _FakeDBLatest:
    def __init__(self, evaluation):
        self.evaluation = evaluation

    def execute(self, _query):
        return _ExecResult([self.evaluation] if self.evaluation else [])


def _ticket() -> SimpleNamespace:
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(
        id="TW-9100",
        jira_key="HP-9100",
        title="Intermittent VPN failure",
        description="VPN drops each hour.",
        status=TicketStatus.open,
        priority="medium",
        category="network",
        assignee="agent@example.com",
        sla_last_synced_at=None,
        sla_first_response_breached=False,
        sla_resolution_breached=False,
        sla_remaining_minutes=35,
        created_at=now - dt.timedelta(hours=8),
        updated_at=now - dt.timedelta(hours=2),
    )


def test_sla_run_dry_run_does_not_commit(monkeypatch) -> None:
    ticket = _ticket()
    db = _FakeDBDryRun(ticket)
    current_user = SimpleNamespace(id="u-1", role=UserRole.admin)

    monkeypatch.setattr("app.routers.sla.sync_ticket_sla", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.routers.sla._sync_succeeded", lambda **_kwargs: True)
    monkeypatch.setattr("app.routers.sla.compute_escalation", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr("app.routers.sla._status_change_stale", lambda *_args, **_kwargs: False)

    result = run_sla_batch(payload=SLABatchRunRequest(limit=1, force=True, dry_run=True), db=db, current_user=current_user)
    assert result["dry_run"] is True
    assert result["synced"] == 1
    assert db.commits == 0
    assert isinstance(result["proposed_actions"], list)


def test_get_latest_ai_risk_endpoint_payload(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    evaluation = SimpleNamespace(
        risk_score=84,
        confidence=0.72,
        suggested_priority="High",
        reasoning_summary="Elevated risk because status has remained unchanged.",
        model_version="gemma:3b",
        decision_source="shadow",
        created_at=now,
    )
    db = _FakeDBLatest(evaluation)
    current_user = SimpleNamespace(id="u-2", role=UserRole.agent)
    ticket = SimpleNamespace(id="TW-9100")
    monkeypatch.setattr("app.routers.sla.get_ticket_for_user", lambda *_args, **_kwargs: ticket)
    monkeypatch.setattr("app.routers.sla._count_similar_incidents", lambda *_args, **_kwargs: 5)
    monkeypatch.setattr("app.routers.sla._count_assignee_active_tickets", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(
        "app.routers.sla.build_sla_advisory",
        lambda *_args, **_kwargs: {
            "risk_score": 0.74,
            "band": "high",
            "confidence": 0.81,
            "reasoning": ["Ticket has consumed 78% of the SLA window.", "No activity recorded in the last 2 hours."],
            "recommended_actions": ["Follow up with the assignee now.", "Reassign if the ticket remains inactive after the follow-up."],
            "advisory_mode": "hybrid",
            "evaluated_at": now.isoformat(),
            "suggested_priority": "High",
            "sla_elapsed_ratio": 0.78,
            "time_consumed_percent": 78,
        },
    )

    payload = get_ticket_ai_risk_latest("TW-9100", db=db, current_user=current_user)
    assert payload["ticket_id"] == "TW-9100"
    assert payload["risk_score"] == 0.74
    assert payload["band"] == "high"
    assert payload["advisory_mode"] == "hybrid"
    assert payload["reasoning"]
    assert payload["recommended_actions"]
    assert payload["model_version"] == "gemma:3b"
    assert "created_at" in payload


def test_build_sla_advisory_returns_deterministic_payload_without_ai() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ticket = _ticket()

    advisory = build_sla_advisory(ticket, similar_incidents=3, assignee_load=2, now=now, lang="en")

    assert advisory["advisory_mode"] == "deterministic"
    assert 0.0 <= advisory["risk_score"] <= 1.0
    assert advisory["band"] in {"low", "medium", "high", "critical"}
    assert any("SLA window" in reason or "activity" in reason.lower() for reason in advisory["reasoning"])
    assert advisory["recommended_actions"]


def test_build_sla_advisory_computes_critical_band_for_breached_ticket() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ticket = _ticket()
    ticket.sla_first_response_breached = True
    ticket.sla_remaining_minutes = 0
    ticket.updated_at = now - dt.timedelta(hours=5)
    ticket.priority = "critical"

    advisory = build_sla_advisory(ticket, similar_incidents=8, assignee_load=6, now=now, lang="en")

    assert advisory["band"] == "critical"
    assert advisory["risk_score"] >= 0.8
    assert any("breached" in reason.lower() for reason in advisory["reasoning"])
    assert advisory["recommended_actions"][0].lower().startswith("escalate")


def test_build_sla_advisory_recommended_actions_vary_by_risk_band() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    low_ticket = _ticket()
    low_ticket.priority = "low"
    low_ticket.sla_elapsed_minutes = 15
    low_ticket.sla_remaining_minutes = 240
    low_ticket.updated_at = now - dt.timedelta(minutes=10)

    low_advisory = build_sla_advisory(low_ticket, similar_incidents=0, assignee_load=1, now=now, lang="en")
    high_ticket = _ticket()
    high_ticket.priority = "critical"
    high_ticket.sla_elapsed_minutes = 200
    high_ticket.sla_remaining_minutes = 20
    high_ticket.updated_at = now - dt.timedelta(hours=3)

    high_advisory = build_sla_advisory(high_ticket, similar_incidents=7, assignee_load=5, now=now, lang="en")

    assert low_advisory["recommended_actions"][0].lower().startswith("no immediate action")
    assert any(action.lower().startswith(("follow up", "escalate")) for action in high_advisory["recommended_actions"])


def test_get_latest_ai_risk_endpoint_returns_deterministic_advisory_without_persisted_eval(monkeypatch) -> None:
    db = _FakeDBLatest(None)
    current_user = SimpleNamespace(id="u-3", role=UserRole.agent)
    ticket = _ticket()
    monkeypatch.setattr("app.routers.sla.get_ticket_for_user", lambda *_args, **_kwargs: ticket)
    monkeypatch.setattr("app.routers.sla._count_similar_incidents", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr("app.routers.sla._count_assignee_active_tickets", lambda *_args, **_kwargs: 3)

    payload = get_ticket_ai_risk_latest("TW-9100", db=db, current_user=current_user)

    assert payload["ticket_id"] == "TW-9100"
    assert payload["advisory_mode"] == "deterministic"
    assert payload["reasoning"]
    assert payload["recommended_actions"]
    assert payload["confidence"] > 0
