from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.enums import SeniorityLevel, UserRole


def _make_client():
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app, raise_server_exceptions=False)


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_db, None)


def _fake_user(*, is_verified: bool, has_password: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        email="user@example.com",
        name="Test User",
        role=UserRole.user,
        is_verified=is_verified,
        created_at=dt.datetime.now(dt.timezone.utc),
        specializations=[],
        seniority_level=SeniorityLevel.middle,
        is_available=True,
        max_concurrent_tickets=10,
        password_hash="hashed-password" if has_password else None,
    )


def test_email_login_rejects_unknown_email_without_creating_account(monkeypatch) -> None:
    from app.routers import auth as auth_router

    create_called = False

    def _create_user(*_args, **_kwargs):
        nonlocal create_called
        create_called = True
        raise AssertionError("email login must not create users")

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auth_router, "create_user", _create_user)

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "new@example.com", "password": "secret123"})
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["message"] == "invalid_credentials"
    assert create_called is False


def test_email_login_rejects_account_without_password_hash(monkeypatch) -> None:
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: _fake_user(is_verified=True, has_password=False))

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "user@example.com", "password": "secret123"})
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["message"] == "invalid_credentials"


def test_email_login_logs_in_verified_user_and_sets_cookies(monkeypatch) -> None:
    from app.routers import auth as auth_router

    user = _fake_user(is_verified=True)

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(
        auth_router,
        "issue_auth_tokens",
        lambda *_args, **_kwargs: SimpleNamespace(access_token="access-token", refresh_token="refresh-token"),
    )

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "user@example.com", "password": "secret123"})
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json()["message"] == "logged_in"
    assert response.json()["user"]["email"] == "user@example.com"
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.COOKIE_NAME in set_cookie
    assert settings.REFRESH_COOKIE_NAME in set_cookie


def test_email_login_resends_verification_for_existing_unverified_user(monkeypatch) -> None:
    from app.routers import auth as auth_router

    user = _fake_user(is_verified=False)
    sent = {"called": False}

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(auth_router, "_send_verification_email", lambda *_args, **_kwargs: sent.__setitem__("called", True))

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "user@example.com", "password": "secret123"})
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json()["message"] == "verification_sent"
    assert response.json()["requires_verification"] is True
    assert sent["called"] is True
    assert settings.COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_email_login_keeps_invalid_credentials_for_wrong_password(monkeypatch) -> None:
    from app.routers import auth as auth_router

    user = _fake_user(is_verified=True)

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *_args, **_kwargs: None)

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "user@example.com", "password": "wrong-pass"})
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["message"] == "invalid_credentials"


def test_email_login_unknown_email_does_not_return_password_too_short(monkeypatch) -> None:
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "find_user_by_email", lambda *_args, **_kwargs: None)

    client = _make_client()
    try:
        response = client.post("/api/auth/email-login", json={"email": "new@example.com", "password": "x"})
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["message"] == "invalid_credentials"
