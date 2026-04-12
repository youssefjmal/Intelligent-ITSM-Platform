from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import deps as deps_module
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.routers import notifications as notifications_router
from app.services import automation_webhooks, notifications_service


class _FakeDB:
    def __init__(self, *, user: SimpleNamespace | None = None) -> None:
        self.user = user
        self.commits = 0

    def get(self, model, key):  # noqa: ANN001
        if model is User and self.user is not None and self.user.id == key:
            return self.user
        return None

    def commit(self) -> None:
        self.commits += 1


def _make_client(db: object) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_automation_secret_no_longer_authenticates_normal_routes(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")

    client = _make_client(_FakeDB())
    try:
        notifications_response = client.get(
            "/api/notifications/unread-count",
            headers={"X-Automation-Secret": "inbound-secret"},
        )
        tickets_response = client.get(
            "/api/tickets/",
            headers={"X-Automation-Secret": "inbound-secret"},
        )
        problems_response = client.get(
            "/api/problems",
            headers={"X-Automation-Secret": "inbound-secret"},
        )
    finally:
        _clear_overrides()

    assert notifications_response.status_code == 401
    assert notifications_response.json()["error_code"] == "NOT_AUTHENTICATED"
    assert tickets_response.status_code == 401
    assert tickets_response.json()["error_code"] == "NOT_AUTHENTICATED"
    assert problems_response.status_code == 401
    assert problems_response.json()["error_code"] == "NOT_AUTHENTICATED"


def test_invalid_bearer_token_does_not_fall_back_to_n8n_secret(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(deps_module, "decode_token", lambda _token: (_ for _ in ()).throw(ValueError("invalid_token")))

    client = _make_client(_FakeDB())
    try:
        response = client.get(
            "/api/notifications/unread-count",
            headers={
                "Authorization": "Bearer broken-token",
                "X-Automation-Secret": "inbound-secret",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_TOKEN"


def test_expired_bearer_token_does_not_fall_back_to_n8n_secret(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(deps_module, "decode_token", lambda _token: (_ for _ in ()).throw(ValueError("expired_token")))

    client = _make_client(_FakeDB())
    try:
        response = client.get(
            "/api/notifications/unread-count",
            headers={
                "Authorization": "Bearer expired-token",
                "X-Automation-Secret": "inbound-secret",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["error_code"] == "EXPIRED_TOKEN"


def test_system_notification_accepts_valid_inbound_secret(monkeypatch) -> None:
    target_user = SimpleNamespace(id=uuid4(), email="agent@example.com", name="Agent One")
    fake_db = _FakeDB(user=target_user)

    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(deps_module.settings, "N8N_OUTBOUND_SECRET", "outbound-secret")
    monkeypatch.setattr(notifications_router, "_dedupe_user_ids", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(notifications_router, "create_notification", lambda *_args, **_kwargs: object())

    client = _make_client(fake_db)
    try:
        response = client.post(
            "/api/notifications/system",
            headers={"X-Automation-Secret": "inbound-secret"},
            json={
                "user_id": str(target_user.id),
                "title": "n8n workflow event",
                "body": "Created by workflow",
                "severity": "warning",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"status": "created", "count": 1}
    assert fake_db.commits == 1


def test_system_notification_rejects_missing_inbound_secret(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")

    client = _make_client(_FakeDB())
    try:
        response = client.post(
            "/api/notifications/system",
            json={"title": "n8n workflow event"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_AUTOMATION_SECRET"


def test_system_notification_rejects_wrong_secret(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(deps_module.settings, "N8N_OUTBOUND_SECRET", "outbound-secret")

    client = _make_client(_FakeDB())
    try:
        response = client.post(
            "/api/notifications/system",
            headers={"X-Automation-Secret": "outbound-secret"},
            json={"title": "n8n workflow event"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_AUTOMATION_SECRET"


def test_system_notification_fails_closed_when_inbound_secret_unset(monkeypatch) -> None:
    monkeypatch.setattr(deps_module.settings, "N8N_INBOUND_SECRET", "")

    client = _make_client(_FakeDB())
    try:
        response = client.post(
            "/api/notifications/system",
            headers={"X-Automation-Secret": "anything"},
            json={"title": "n8n workflow event"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 400
    assert response.json()["message"] == "n8n_inbound_secret_not_configured"


def test_notification_outbound_webhook_uses_outbound_secret(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _Response:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json, headers):  # noqa: ANN001
            captured["url"] = url
            captured["secret"] = headers.get("X-Automation-Secret", "")
            return _Response()

    monkeypatch.setattr(notifications_service.settings, "N8N_WEBHOOK_BASE_URL", "http://example.test/webhooks")
    monkeypatch.setattr(notifications_service.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(notifications_service.settings, "N8N_OUTBOUND_SECRET", "outbound-secret")
    monkeypatch.setattr(notifications_service.httpx, "Client", _Client)

    ok, error = notifications_service._dispatch_n8n_notification(
        notification=SimpleNamespace(
            id=uuid4(),
            event_type=notifications_service.EVENT_SLA_BREACHED,
            title="Critical SLA breach",
            body="Workflow escalation",
            severity="critical",
            source="sla",
            link="/tickets/TW-1",
            metadata_json={},
            action_payload={},
        ),
        user=SimpleNamespace(id=uuid4(), email="agent@example.com", name="Agent One"),
    )

    assert ok is True
    assert error is None
    assert captured["secret"] == "outbound-secret"


def test_automation_webhook_post_uses_outbound_secret(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _Response:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json, headers):  # noqa: ANN001
            captured["url"] = url
            captured["secret"] = headers.get("X-Automation-Secret", "")
            return _Response()

    monkeypatch.setattr(automation_webhooks.settings, "N8N_WEBHOOK_BASE_URL", "http://example.test/webhooks")
    monkeypatch.setattr(automation_webhooks.settings, "N8N_INBOUND_SECRET", "inbound-secret")
    monkeypatch.setattr(automation_webhooks.settings, "N8N_OUTBOUND_SECRET", "outbound-secret")
    monkeypatch.setattr(automation_webhooks.httpx, "Client", _Client)

    assert automation_webhooks._post("critical-ticket-detected", {"ticket_id": "TW-1"}) is True
    assert captured["secret"] == "outbound-secret"


def test_settings_warn_when_n8n_inbound_secret_missing_in_production() -> None:
    from app.core.config import Settings

    settings = Settings(
        ENV="production",
        JWT_SECRET="x" * 32,
        PROMETHEUS_METRICS_ENABLED=False,
        N8N_INBOUND_SECRET="",
    )

    with pytest.warns(UserWarning, match="N8N_INBOUND_SECRET is not set"):
        settings.validate_runtime_security()


def test_docker_compose_passes_split_n8n_secrets_to_backend() -> None:
    compose_text = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")

    assert "N8N_INBOUND_SECRET" in compose_text
    assert "N8N_OUTBOUND_SECRET" in compose_text
