from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketStatus, UserRole
from app.routers.sla import SLABatchRunRequest, get_ticket_ai_risk_latest, run_sla_batch


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

    payload = get_ticket_ai_risk_latest("TW-9100", db=db, current_user=current_user)
    assert payload["ticket_id"] == "TW-9100"
    assert payload["risk_score"] == 84
    assert payload["model_version"] == "gemma:3b"
    assert "created_at" in payload
