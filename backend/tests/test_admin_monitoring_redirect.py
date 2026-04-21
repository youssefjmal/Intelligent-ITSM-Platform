from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import require_admin
from app.routers import security as security_router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(security_router.router, prefix="/api/admin")
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def test_monitoring_dashboards_returns_configured_urls(monkeypatch) -> None:
    monkeypatch.setattr(security_router.settings, "GRAFANA_BASE_URL", "http://grafana.internal:3000")
    monkeypatch.setattr(security_router.settings, "PROMETHEUS_BASE_URL", "http://prometheus.internal:9090")
    client = _make_client()

    response = client.get("/api/admin/monitoring/dashboards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["grafana_url"] == "http://grafana.internal:3000"
    assert payload["prometheus_url"] == "http://prometheus.internal:9090"
    assert any(item["name"] == "grafana" and item["url"] == "http://grafana.internal:3000" for item in payload["items"])


def test_monitoring_grafana_redirects_to_configured_url(monkeypatch) -> None:
    monkeypatch.setattr(security_router.settings, "GRAFANA_BASE_URL", "http://grafana.internal:3000")
    client = _make_client()

    response = client.get("/api/admin/monitoring/grafana", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://grafana.internal:3000"
