from __future__ import annotations

from fastapi.testclient import TestClient
import pytest


def _make_client() -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_metrics_requires_authorization(monkeypatch) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    client = _make_client()
    response = client.get("/metrics")

    assert response.status_code == 401


def test_metrics_rejects_wrong_token(monkeypatch) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    client = _make_client()
    response = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


def test_metrics_returns_prometheus_payload_for_valid_token(monkeypatch) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    client = _make_client()
    response = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP" in response.text or "# TYPE" in response.text


def test_metrics_returns_not_found_when_disabled(monkeypatch) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_ENABLED", False)
    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    client = _make_client()
    response = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert response.status_code == 404


def test_metrics_returns_service_unavailable_when_token_unset(monkeypatch) -> None:
    from app.main import settings

    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "PROMETHEUS_METRICS_TOKEN", "")

    client = _make_client()
    response = client.get("/metrics")

    assert response.status_code == 503


def test_settings_warn_when_metrics_enabled_without_token_in_development() -> None:
    from app.core.config import Settings

    settings = Settings(
        ENV="development",
        JWT_SECRET="x" * 32,
        PROMETHEUS_METRICS_ENABLED=True,
        PROMETHEUS_METRICS_TOKEN="",
    )

    with pytest.warns(UserWarning, match="PROMETHEUS_METRICS_TOKEN is required"):
        settings.validate_runtime_security()


def test_settings_warn_when_metrics_token_uses_known_default_in_development() -> None:
    from app.core.config import Settings

    settings = Settings(
        ENV="development",
        JWT_SECRET="x" * 32,
        PROMETHEUS_METRICS_ENABLED=True,
        PROMETHEUS_METRICS_TOKEN="local-prom-scrape-token",
    )

    with pytest.warns(UserWarning, match="PROMETHEUS_METRICS_TOKEN is too weak"):
        settings.validate_runtime_security()


def test_settings_fail_when_metrics_enabled_without_token_in_production() -> None:
    from app.core.config import Settings

    settings = Settings(
        ENV="production",
        JWT_SECRET="x" * 32,
        PROMETHEUS_METRICS_ENABLED=True,
        PROMETHEUS_METRICS_TOKEN="",
    )

    with pytest.raises(ValueError, match="PROMETHEUS_METRICS_TOKEN is required"):
        settings.validate_runtime_security()


def test_settings_fail_when_metrics_token_uses_known_default_in_production() -> None:
    from app.core.config import Settings

    settings = Settings(
        ENV="production",
        JWT_SECRET="x" * 32,
        PROMETHEUS_METRICS_ENABLED=True,
        PROMETHEUS_METRICS_TOKEN="local-prom-scrape-token",
    )

    with pytest.raises(ValueError, match="PROMETHEUS_METRICS_TOKEN is too weak"):
        settings.validate_runtime_security()
