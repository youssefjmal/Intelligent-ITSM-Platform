from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.models.enums import SeniorityLevel, UserRole
from app.main import app
from app.routers import auth as auth_router


def _make_user(*, email: str, is_verified: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        email=email,
        name="Test User",
        role=UserRole.user,
        is_verified=is_verified,
        created_at=dt.datetime(2026, 4, 9, 12, 0, tzinfo=dt.timezone.utc),
        specializations=[],
        seniority_level=SeniorityLevel.intern,
        is_available=True,
        max_concurrent_tickets=10,
        password_hash="hashed-password",
    )


def _make_client() -> TestClient:
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app, raise_server_exceptions=False)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_email_login_logs_in_verified_user_and_sets_cookies(monkeypatch) -> None:
    user = _make_user(email="verified@example.com", is_verified=True)

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: user)
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *args, **kwargs: user)
    monkeypatch.setattr(
        auth_router,
        "issue_auth_tokens",
        lambda db, current_user: SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=current_user,
        ),
    )

    client = _make_client()
    try:
        response = client.post(
            "/api/auth/email-login",
            json={"email": user.email, "password": "super-secret-password"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json()["message"] == "logged_in"
    assert response.json()["requires_verification"] is False
    set_cookie = response.headers.get("set-cookie", "")
    assert auth_router.settings.COOKIE_NAME in set_cookie
    assert auth_router.settings.REFRESH_COOKIE_NAME in set_cookie


def test_email_login_resends_verification_for_existing_unverified_user(monkeypatch) -> None:
    user = _make_user(email="pending@example.com", is_verified=False)
    send_calls: list[str] = []

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: user)
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *args, **kwargs: user)
    monkeypatch.setattr(auth_router, "_send_verification_email", lambda db, current_user: send_calls.append(current_user.email))

    client = _make_client()
    try:
        response = client.post(
            "/api/auth/email-login",
            json={"email": user.email, "password": "super-secret-password"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json() == {
        "message": "verification_sent",
        "user": None,
        "requires_verification": True,
    }
    assert send_calls == [user.email]
    assert "set-cookie" not in response.headers


def test_email_login_unknown_email_returns_invalid_credentials_without_signup(monkeypatch) -> None:
    create_attempts: list[str] = []

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: None)
    monkeypatch.setattr(auth_router, "create_user", lambda *args, **kwargs: create_attempts.append("create_user"))
    monkeypatch.setattr(auth_router, "_send_verification_email", lambda *args, **kwargs: create_attempts.append("send_verification"))

    client = _make_client()
    try:
        response = client.post(
            "/api/auth/email-login",
            json={"email": "unknown@example.com", "password": "12345678"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401
    assert response.json()["message"] == "invalid_credentials"
    assert create_attempts == []


def test_email_login_wrong_password_matches_unknown_email_response(monkeypatch) -> None:
    user = _make_user(email="verified@example.com", is_verified=True)

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(
        auth_router,
        "find_user_by_email",
        lambda db, email: user if email == user.email else None,
    )
    monkeypatch.setattr(auth_router, "authenticate_user", lambda *args, **kwargs: None)

    client = _make_client()
    try:
        wrong_password = client.post(
            "/api/auth/email-login",
            json={"email": user.email, "password": "wrong-password"},
        )
        unknown_email = client.post(
            "/api/auth/email-login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )
    finally:
        _clear_overrides()

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["message"] == unknown_email.json()["message"] == "invalid_credentials"


def test_email_login_locked_account_response_is_preserved(monkeypatch) -> None:
    user = _make_user(email="locked@example.com", is_verified=True)

    def fake_authenticate(*args, **kwargs):
        raise ValueError("account_locked:15")

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: user)
    monkeypatch.setattr(auth_router, "authenticate_user", fake_authenticate)

    client = _make_client()
    try:
        response = client.post(
            "/api/auth/email-login",
            json={"email": user.email, "password": "super-secret-password"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 423
    assert response.json()["message"] == "account_locked_15min"


def test_email_login_short_password_unknown_email_returns_invalid_credentials(monkeypatch) -> None:
    """Login no longer behaves like sign-up: a short password for an unknown
    email must return the same invalid_credentials 401 — not password_too_short —
    because we refuse to reveal whether the email exists or not."""
    create_attempts: list[str] = []

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: None)
    # Guard: if create_user is somehow called the test will catch it
    monkeypatch.setattr(auth_router, "create_user", lambda *args, **kwargs: create_attempts.append("create_user"))

    client = _make_client()
    try:
        response = client.post(
            "/api/auth/email-login",
            json={"email": "newperson@example.com", "password": "short"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 401, (
        f"Expected 401 invalid_credentials for unknown email with short password, got {response.status_code}"
    )
    assert response.json()["message"] == "invalid_credentials", (
        "Login must not return 'password_too_short' — that would reveal sign-up semantics"
    )
    assert create_attempts == [], "No user should have been created"


def test_email_login_no_user_row_created_for_unknown_email(monkeypatch) -> None:
    """Calling /email-login with a brand-new email must not create any user row,
    regardless of whether the password meets length requirements."""
    created_rows: list[str] = []

    monkeypatch.setattr(auth_router.settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(auth_router, "find_user_by_email", lambda db, email: None)
    monkeypatch.setattr(auth_router, "create_user", lambda *a, **kw: created_rows.append("create_user"))
    monkeypatch.setattr(auth_router, "_send_verification_email", lambda *a, **kw: created_rows.append("send_verification"))

    client = _make_client()
    try:
        for password in ("short", "longpassword123", "exactly8"):
            client.post(
                "/api/auth/email-login",
                json={"email": "phantom@example.com", "password": password},
            )
    finally:
        _clear_overrides()

    assert created_rows == [], (
        f"Expected no user creation side-effects, but got: {created_rows}"
    )
