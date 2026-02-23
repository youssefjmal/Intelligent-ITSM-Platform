from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketStatus, UserRole
from app.routers.sla import SLABatchRunRequest, _persist_ai_risk_evaluation, run_sla_batch
from app.services.ai import ai_sla_risk


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

    def scalar(self):
        if isinstance(self._values, list):
            return self._values[0] if self._values else None
        return self._values


class _FakeDB:
    def __init__(self, ticket):
        self.ticket = ticket
        self.added = []

    def execute(self, _query):
        return _ExecResult([self.ticket.id])

    def get(self, _model, _key):
        return self.ticket

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None


def _ticket() -> SimpleNamespace:
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(
        id="TW-9001",
        jira_key="HP-9001",
        title="VPN disconnects frequently",
        description="User reports VPN disconnect every hour.",
        status=TicketStatus.open,
        priority="medium",
        category="network",
        assignee="agent@example.com",
        sla_last_synced_at=None,
        sla_first_response_breached=False,
        sla_resolution_breached=False,
        sla_remaining_minutes=45,
        created_at=now - dt.timedelta(hours=6),
        updated_at=now - dt.timedelta(hours=1),
    )


def test_ai_sla_risk_json_parsing_safety(monkeypatch) -> None:
    ticket = _ticket()
    monkeypatch.setattr(ai_sla_risk, "ollama_generate", lambda *_args, **_kwargs: '{"risk_score":82,"confidence":0.73,"suggested_priority":"High","reasoning_summary":"Risk rising due to aging status."}')
    result = ai_sla_risk.evaluate_sla_risk(ticket, assignee_role="network", similar_incidents=3)
    assert result["risk_score"] == 82
    assert result["confidence"] == 0.73
    assert result["suggested_priority"] == "High"


def test_ai_sla_risk_fallback_on_invalid_llm_payload(monkeypatch) -> None:
    ticket = _ticket()
    monkeypatch.setattr(ai_sla_risk, "ollama_generate", lambda *_args, **_kwargs: "not-json")
    result = ai_sla_risk.evaluate_sla_risk(ticket, assignee_role="network", similar_incidents=1)
    assert result["risk_score"] is None
    assert result["confidence"] is None


def test_persist_ai_sla_risk_evaluation() -> None:
    ticket = _ticket()
    db = _FakeDB(ticket)
    _persist_ai_risk_evaluation(
        db,
        ticket=ticket,
        evaluation={
            "risk_score": 88,
            "confidence": 0.8,
            "suggested_priority": "High",
            "reasoning_summary": "SLA window is tightening.",
            "model_version": "gemma:3b",
        },
        decision_source="shadow",
    )
    assert len(db.added) == 1
    saved = db.added[0]
    assert str(saved.ticket_id) == ticket.id
    assert saved.risk_score == 88
    assert saved.decision_source == "shadow"


def test_run_sla_batch_includes_ai_risk_summary(monkeypatch) -> None:
    ticket = _ticket()
    db = _FakeDB(ticket)
    current_user = SimpleNamespace(id="u-1", role=UserRole.admin)

    monkeypatch.setattr("app.routers.sla.sync_ticket_sla", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.routers.sla._sync_succeeded", lambda **_kwargs: True)
    monkeypatch.setattr("app.routers.sla.apply_escalation", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("app.routers.sla._status_change_stale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("app.routers.sla._resolve_assignee_role", lambda *_args, **_kwargs: "network")
    monkeypatch.setattr("app.routers.sla._count_similar_incidents", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr("app.routers.sla._snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.routers.sla.settings.AI_SLA_RISK_ENABLED", True)
    monkeypatch.setattr(
        "app.routers.sla.evaluate_sla_risk",
        lambda *_args, **_kwargs: {
            "risk_score": 90,
            "confidence": 0.77,
            "suggested_priority": "High",
            "reasoning_summary": "Ticket is likely to breach.",
            "model_version": "gemma:3b",
        },
    )

    payload = SLABatchRunRequest(limit=1, force=True)
    result = run_sla_batch(payload=payload, db=db, current_user=current_user)
    assert "ai_risk_summary" in result
    assert result["ai_risk_summary"]["evaluated"] == 1
    assert result["ai_risk_summary"]["high_risk_detected"] == 1
