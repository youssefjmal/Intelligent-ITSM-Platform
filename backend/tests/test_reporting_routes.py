from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.routers import sla as sla_router
from app.routers import tickets as tickets_router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(tickets_router.router, prefix="/api/tickets")
    app.include_router(sla_router.router, prefix="/api/sla")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1",
        role=UserRole.admin,
    )
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return app


def test_tickets_insights_route_returns_expected_sections(monkeypatch) -> None:
    monkeypatch.setattr(tickets_router._cache, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tickets_router._cache, "set", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda *_args, **_kwargs: ["ticket"])
    monkeypatch.setattr(tickets_router, "compute_weekly_trends", lambda tickets: [{"week": "2026-W01", "opened": 1, "closed": 1, "pending": 0}])
    monkeypatch.setattr(tickets_router, "compute_type_breakdown", lambda tickets: [{"type": "incident", "count": 1}])
    monkeypatch.setattr(tickets_router, "compute_category_breakdown", lambda tickets: [{"category": "network", "count": 1}])
    monkeypatch.setattr(tickets_router, "compute_priority_breakdown", lambda tickets: [{"priority": "high", "count": 1, "color": "#f00"}])
    monkeypatch.setattr(tickets_router, "compute_problem_insights", lambda tickets: [{"problem_id": "PB-1", "count": 1}])
    monkeypatch.setattr(tickets_router, "problem_analytics_summary", lambda db: {"total_problems": 1})
    monkeypatch.setattr(tickets_router, "compute_operational_insights", lambda tickets: {"queue_depth": 1})
    monkeypatch.setattr(tickets_router, "compute_assignment_performance", lambda tickets, **kwargs: {"total_tickets": 1})

    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/api/tickets/insights")

    assert response.status_code == 200
    payload = response.json()
    assert "weekly" in payload
    assert "performance" in payload
    assert "operational" in payload


def test_tickets_performance_route_returns_metrics(monkeypatch) -> None:
    monkeypatch.setattr(tickets_router._cache, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tickets_router._cache, "set", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda *_args, **_kwargs: ["ticket"])
    monkeypatch.setattr(
        tickets_router,
        "compute_assignment_performance",
        lambda tickets, **kwargs: {
            "total_tickets": 4,
            "resolved_tickets": 2,
            "mttr_hours": {"before": 12.0, "after": 8.0},
            "mttr_global_hours": 10.0,
            "mttr_p90_hours": 16.0,
            "mttr_by_priority_hours": {"high": 10.0},
            "mttr_by_category_hours": {"network": 9.0},
            "throughput_resolved_per_week": 3,
            "backlog_open_over_days": 1,
            "backlog_threshold_days": 7,
            "reassignment_rate": 25.0,
            "reassigned_tickets": 1,
            "avg_time_to_first_action_hours": 1.5,
            "median_time_to_first_action_hours": 1.0,
            "classification_accuracy_rate": 90.0,
            "classification_samples": 4,
            "high_confidence_rate": 50.0,
            "low_confidence_rate": 10.0,
            "classification_correction_count": 1,
            "auto_assignment_accuracy_rate": 100.0,
            "auto_assignment_samples": 2,
            "auto_triage_no_correction_rate": 100.0,
            "auto_triage_no_correction_count": 2,
            "auto_triage_samples": 2,
            "sla_breach_rate": 0.0,
            "sla_breached_tickets": 0,
            "sla_tickets_with_due": 4,
            "first_response_sla_breach_rate": 0.0,
            "first_response_sla_breached_count": 0,
            "first_response_sla_eligible": 4,
            "resolution_sla_breach_rate": 0.0,
            "resolution_sla_breached_count": 0,
            "resolution_sla_eligible": 4,
            "reopen_rate": 0.0,
            "first_contact_resolution_rate": 0.5,
            "csat_score": None,
        },
    )

    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/api/tickets/performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tickets"] == 4
    assert payload["throughput_resolved_per_week"] == 3


def test_tickets_agent_performance_route_returns_agents(monkeypatch) -> None:
    monkeypatch.setattr(tickets_router._cache, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tickets_router._cache, "set", lambda *_args, **_kwargs: True)
    now = dt.datetime.now(dt.timezone.utc)
    sample_ticket = SimpleNamespace(
        assignee="Agent One",
        created_at=now - dt.timedelta(days=2),
        resolved_at=now - dt.timedelta(days=1),
        first_action_at=now - dt.timedelta(days=2, hours=-1),
        status=SimpleNamespace(value="resolved"),
        sla_resolution_breached=False,
    )
    monkeypatch.setattr(tickets_router, "list_tickets_for_user", lambda *_args, **_kwargs: [sample_ticket])

    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/api/tickets/agent-performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["period_days"] == 30
    assert payload["agents"][0]["agent_name"] == "Agent One"


def test_sla_metrics_route_returns_summary(monkeypatch) -> None:
    db = MagicMock()
    app = _make_app()
    app.dependency_overrides[get_db] = lambda: db

    rows = [
        SimpleNamespace(sla_status="ok", sla_remaining_minutes=40),
        SimpleNamespace(sla_status="breached", sla_remaining_minutes=0),
    ]
    db.execute.return_value.scalars.return_value.all.return_value = rows

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/sla/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tickets"] == 2
    assert payload["sla_breakdown"]["breached"] == 1
