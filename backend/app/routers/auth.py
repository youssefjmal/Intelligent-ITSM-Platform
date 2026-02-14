"""Authentication endpoints (register, login, verify, logout)."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import AuthenticationException, BadRequestError, ConflictError, NotFoundError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.enums import EmailKind
from app.models.user import User
from app.schemas.auth import (
    EmailLoginResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    ResendVerificationRequest,
    TokenRefreshRequest,
    TokenResponse,
    VerificationCodeRequest,
    VerificationRequest,
    VerificationResponse,
)
from app.schemas.user import UserCreate, UserLogin, UserOut
from app.services.auth import (
    authenticate_user,
    create_password_reset_token,
    create_or_update_user_from_google,
    create_user_from_email_password,
    create_user,
    create_verification_token,
    find_user_by_email,
    issue_auth_tokens,
    revoke_refresh_token,
    reset_password_with_token,
    rotate_refresh_token,
    verify_email_token,
    verify_email_code,
)
from app.services.email import build_password_reset_email, build_verification_email, build_welcome_email, log_email

router = APIRouter(dependencies=[Depends(rate_limit("auth"))])
logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OAUTH_STATE_COOKIE = "tw_oauth_state"


def _set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    is_secure = settings.ENV != "development"
    response.set_cookie(
        settings.COOKIE_NAME,
        access_token,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/api/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path="/api/auth")


def _validate_credentials(db: Session, payload: UserLogin) -> User:
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise AuthenticationException("invalid_credentials", error_code="INVALID_CREDENTIALS", status_code=401)
    if not user.is_verified:
        raise AuthenticationException("email_not_verified", error_code="EMAIL_NOT_VERIFIED", status_code=403)
    return user


def _send_verification_email(db: Session, user: User) -> tuple[str | None, str | None]:
    token = create_verification_token(db, user)
    subject, body, html_body = build_verification_email(user.name, token.token, token.code)
    log_email(db, user.email, subject, body, EmailKind.verification, html_body=html_body)
    if settings.ENV == "development":
        return token.token, token.code
    return None, None


def _oauth_is_configured() -> bool:
    return bool(
        settings.GOOGLE_CLIENT_ID.strip()
        and settings.GOOGLE_CLIENT_SECRET.strip()
        and settings.GOOGLE_REDIRECT_URI.strip()
    )


def _oauth_error_redirect(error_code: str) -> RedirectResponse:
    query = urlencode({"oauth_error": error_code})
    return RedirectResponse(url=f"{settings.FRONTEND_BASE_URL}/auth/login?{query}", status_code=302)


def _clear_google_state_cookie(response: Response) -> None:
    response.delete_cookie(GOOGLE_OAUTH_STATE_COOKIE, path="/api/auth/google")


@router.post("/register", response_model=RegisterResponse)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> RegisterResponse:
    if find_user_by_email(db, payload.email):
        raise ConflictError("email_exists", details={"email": payload.email.lower()})

    user = create_user(db, payload)
    verification_token, verification_code = _send_verification_email(db, user)
    return RegisterResponse(
        message="verification_sent",
        verification_token=verification_token,
        verification_code=verification_code,
    )


@router.post("/login", response_model=UserOut)
def login_user(payload: UserLogin, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = _validate_credentials(db, payload)
    tokens = issue_auth_tokens(db, user)
    _set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    return UserOut.model_validate(user)


@router.post("/email-login", response_model=EmailLoginResponse)
def email_login(payload: UserLogin, response: Response, db: Session = Depends(get_db)) -> EmailLoginResponse:
    user = find_user_by_email(db, payload.email)

    if user:
        if not user.password_hash:
            raise AuthenticationException("invalid_credentials", error_code="INVALID_CREDENTIALS", status_code=401)

        authenticated_user = authenticate_user(db, payload.email, payload.password)
        if not authenticated_user:
            raise AuthenticationException("invalid_credentials", error_code="INVALID_CREDENTIALS", status_code=401)

        if not authenticated_user.is_verified:
            verification_token, verification_code = _send_verification_email(db, authenticated_user)
            return EmailLoginResponse(
                message="verification_sent",
                requires_verification=True,
                verification_token=verification_token,
                verification_code=verification_code,
            )

        tokens = issue_auth_tokens(db, authenticated_user)
        _set_auth_cookies(
            response,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
        return EmailLoginResponse(message="logged_in", user=UserOut.model_validate(authenticated_user))

    if len(payload.password) < 8:
        raise BadRequestError("password_too_short")

    created_user = create_user_from_email_password(db, payload.email, payload.password)
    verification_token, verification_code = _send_verification_email(db, created_user)
    return EmailLoginResponse(
        message="account_created_verification_sent",
        requires_verification=True,
        verification_token=verification_token,
        verification_code=verification_code,
    )


@router.get("/google/start")
def google_oauth_start() -> RedirectResponse:
    if not _oauth_is_configured():
        return _oauth_error_redirect("google_oauth_not_configured")

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    redirect = RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    redirect.set_cookie(
        GOOGLE_OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=settings.ENV != "development",
        path="/api/auth/google",
        max_age=600,
    )
    return redirect


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        response = _oauth_error_redirect("google_authorization_denied")
        _clear_google_state_cookie(response)
        return response

    if not _oauth_is_configured():
        response = _oauth_error_redirect("google_oauth_not_configured")
        _clear_google_state_cookie(response)
        return response

    stored_state = request.cookies.get(GOOGLE_OAUTH_STATE_COOKIE)
    if not code or not state or not stored_state or state != stored_state:
        response = _oauth_error_redirect("google_invalid_state")
        _clear_google_state_cookie(response)
        return response

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token")
            if not access_token:
                raise ValueError("missing_google_access_token")

            profile_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
    except Exception:
        logger.exception("Google OAuth exchange failed")
        response = _oauth_error_redirect("google_exchange_failed")
        _clear_google_state_cookie(response)
        return response

    google_id = str(profile.get("sub") or "").strip()
    email = str(profile.get("email") or "").strip().lower()
    name = str(profile.get("name") or "").strip() or None
    email_verified = bool(profile.get("email_verified"))

    if not google_id or not email:
        response = _oauth_error_redirect("google_profile_incomplete")
        _clear_google_state_cookie(response)
        return response
    if not email_verified:
        response = _oauth_error_redirect("google_email_not_verified")
        _clear_google_state_cookie(response)
        return response

    try:
        user = create_or_update_user_from_google(
            db,
            google_id=google_id,
            email=email,
            name=name,
            email_verified=email_verified,
        )
    except ValueError as exc:
        error_map = {
            "google_email_conflict": "google_email_conflict",
            "google_id_conflict": "google_account_conflict",
            "google_email_missing": "google_profile_incomplete",
            "google_sub_missing": "google_profile_incomplete",
        }
        response = _oauth_error_redirect(error_map.get(str(exc), "google_oauth_failed"))
        _clear_google_state_cookie(response)
        return response

    tokens = issue_auth_tokens(db, user)
    response = RedirectResponse(url=f"{settings.FRONTEND_BASE_URL}/", status_code=302)
    _set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    _clear_google_state_cookie(response)
    return response


@router.post("/token", response_model=TokenResponse)
def login_for_bearer_tokens(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = _validate_credentials(db, payload)
    tokens = issue_auth_tokens(db, user)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/refresh")
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise AuthenticationException("not_authenticated", error_code="NOT_AUTHENTICATED", status_code=401)

    try:
        tokens = rotate_refresh_token(db, refresh_token)
    except ValueError as exc:
        if str(exc) == "expired_token":
            raise AuthenticationException("refresh_token_expired", error_code="EXPIRED_TOKEN", status_code=401)
        raise AuthenticationException("invalid_refresh_token", error_code="INVALID_TOKEN", status_code=401)

    _set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    return {"message": "refreshed"}


@router.post("/token/refresh", response_model=TokenResponse)
def refresh_bearer_tokens(payload: TokenRefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        tokens = rotate_refresh_token(db, payload.refresh_token)
    except ValueError as exc:
        if str(exc) == "expired_token":
            raise AuthenticationException("refresh_token_expired", error_code="EXPIRED_TOKEN", status_code=401)
        raise AuthenticationException("invalid_refresh_token", error_code="INVALID_TOKEN", status_code=401)

    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/logout")
def logout_user(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if refresh_token:
        revoke_refresh_token(db, refresh_token)
    _clear_auth_cookies(response)
    return {"message": "logged_out"}


@router.get("/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/verify", response_model=VerificationResponse)
def verify_email(payload: VerificationRequest, response: Response, db: Session = Depends(get_db)) -> VerificationResponse:
    user = verify_email_token(db, payload.token)
    if not user:
        raise BadRequestError("invalid_or_expired_token")

    subject, body, html_body = build_welcome_email(user.name)
    log_email(db, user.email, subject, body, EmailKind.welcome, html_body=html_body)
    tokens = issue_auth_tokens(db, user)
    _set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )

    return VerificationResponse(
        message="email_verified",
        auto_logged_in=True,
        user=UserOut.model_validate(user),
    )


@router.post("/verify-code", response_model=VerificationResponse)
def verify_email_with_code(
    payload: VerificationCodeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> VerificationResponse:
    user = verify_email_code(db, payload.email, payload.code)
    if not user:
        raise BadRequestError("invalid_or_expired_verification_code")

    subject, body, html_body = build_welcome_email(user.name)
    log_email(db, user.email, subject, body, EmailKind.welcome, html_body=html_body)
    tokens = issue_auth_tokens(db, user)
    _set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    return VerificationResponse(
        message="email_verified",
        auto_logged_in=True,
        user=UserOut.model_validate(user),
    )


@router.post("/resend", response_model=RegisterResponse)
def resend_verification(payload: ResendVerificationRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    user = find_user_by_email(db, payload.email)
    if not user:
        raise NotFoundError("user_not_found", details={"email": payload.email.lower()})
    if user.is_verified:
        raise ConflictError("already_verified", details={"email": payload.email.lower()})

    verification_token, verification_code = _send_verification_email(db, user)
    return RegisterResponse(
        message="verification_sent",
        verification_token=verification_token,
        verification_code=verification_code,
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> ForgotPasswordResponse:
    user = find_user_by_email(db, payload.email)
    if not user:
        return ForgotPasswordResponse(message="password_reset_sent")

    token = create_password_reset_token(db, user)
    subject, body, html_body = build_password_reset_email(user.name, token.token)
    # Reuse existing email kind to avoid enum migrations for email logs.
    log_email(db, user.email, subject, body, EmailKind.verification, html_body=html_body)
    return ForgotPasswordResponse(message="password_reset_sent")


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> ResetPasswordResponse:
    user = reset_password_with_token(db, payload.token, payload.new_password)
    if not user:
        raise BadRequestError("invalid_or_expired_reset_token")
    return ResetPasswordResponse(message="password_reset_success")
