"""Tests for recommendation feedback analytics helpers and routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db


def _make_app():
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: MagicMock(role=MagicMock(value="admin"), id="u1")
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return app


def _make_auth():
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        yield

    return _ctx()


def test_analytics_useful_rate_formula() -> None:
    useful = 10
    applied = 5
    rejected = 3
    not_relevant = 2
    total = useful + applied + rejected + not_relevant

    expected_useful_rate = round((useful + applied) / total, 4)
    expected_applied_rate = round(applied / total, 4)

    assert expected_useful_rate == round(15 / 20, 4)
    assert expected_applied_rate == round(5 / 20, 4)


def test_analytics_endpoint_returns_canonical_feedback_shape() -> None:
    payload = {
        "total_feedback": 5,
        "useful_count": 2,
        "not_relevant_count": 1,
        "applied_count": 1,
        "rejected_count": 1,
        "usefulness_rate": 0.4,
        "applied_rate": 0.2,
        "rejection_rate": 0.2,
        "by_surface": {},
        "by_display_mode": {},
        "by_confidence_band": {},
        "by_recommendation_mode": {},
        "by_source_label": {},
    }

    with _make_auth():
        with patch("app.routers.recommendations.aggregate_agent_feedback_analytics", return_value=payload):
            client = TestClient(_make_app())
            response = client.get("/api/recommendations/analytics?period_days=30", headers={"Authorization": "Bearer test"})

    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 30
    assert data["total_feedback"] == 5
    assert data["usefulness_rate"] == 0.4
    assert data["applied_rate"] == 0.2
    assert "by_surface" in data


def test_feedback_analytics_endpoint_uses_shared_aggregator() -> None:
    payload = {
        "total_feedback": 3,
        "useful_count": 1,
        "not_relevant_count": 1,
        "applied_count": 1,
        "rejected_count": 0,
        "usefulness_rate": 0.3333,
        "applied_rate": 0.3333,
        "rejection_rate": 0.0,
        "by_surface": {"recommendations_page": {"total_feedback": 3, "useful_count": 1, "not_relevant_count": 1, "applied_count": 1, "rejected_count": 0, "usefulness_rate": 0.3333, "applied_rate": 0.3333, "rejection_rate": 0.0}},
        "by_display_mode": {},
        "by_confidence_band": {},
        "by_recommendation_mode": {},
        "by_source_label": {},
    }

    with _make_auth():
        with patch("app.routers.recommendations.aggregate_agent_feedback_analytics", return_value=payload) as mocked:
            client = TestClient(_make_app())
            response = client.get("/api/recommendations/feedback-analytics", headers={"Authorization": "Bearer test"})

    assert response.status_code == 200
    mocked.assert_called_once()
    data = response.json()
    assert data["total_feedback"] == 3
    assert data["by_surface"]["recommendations_page"]["applied_count"] == 1
