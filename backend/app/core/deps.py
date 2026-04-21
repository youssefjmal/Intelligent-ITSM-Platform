"""Common FastAPI dependencies for authentication and authorization.

Authentication flow
-------------------
Every protected endpoint uses ``get_current_user`` as a FastAPI dependency.
The dependency checks two token sources in order:

  1. ``Authorization: Bearer <token>`` header  — used by API clients and the
     Next.js frontend when making fetch() calls with ``credentials: "include"``.
  2. HttpOnly cookie (``tw_access``) — set by the login endpoint and sent
     automatically by the browser on every same-site request, making it
     invisible to JavaScript (XSS protection).

Access tokens are short-lived JWTs (default: 60 min).  When they expire the
frontend hits ``POST /auth/refresh`` (using the ``tw_refresh`` HttpOnly cookie)
to get a new access token without re-entering credentials.

Machine-to-machine (n8n)
-------------------------
Automation endpoints (e.g. ``POST /notifications/system``) use a separate
shared-secret scheme instead of user JWTs.  The secret is compared with
``hmac.compare_digest`` to prevent timing-oracle attacks.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthenticationException, BadRequestError, ExpiredTokenError, InsufficientPermissionsError
from app.core.metrics import n8n_machine_auth_total
from app.core.rbac import has_permission
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User

logger = logging.getLogger(__name__)


def _extract_bearer_token(request: Request) -> str | None:
    """Pull the raw JWT from the Authorization header, or None if absent/malformed.

    Only accepts the ``Bearer`` scheme — rejects ``Basic``, ``Digest``, etc.
    Returns None (not an error) so the caller can fall through to the cookie.
    """
    authorization = request.headers.get("Authorization", "")
    if not authorization:
        return None
    # partition splits on the first space: "Bearer <token>" → ("Bearer", " ", "<token>")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    cleaned = token.strip()
    return cleaned or None


def _n8n_inbound_secret_matches(candidate: str | None) -> bool:
    """Constant-time comparison of the provided secret against the configured one.

    Uses hmac.compare_digest instead of ``==`` to prevent timing attacks where
    an attacker guesses the secret one byte at a time by measuring response
    latency differences.
    """
    configured = settings.N8N_INBOUND_SECRET.strip()
    provided = (candidate or "").strip()
    # Both sides must be non-empty — comparing empty strings would trivially match.
    if not configured:
        return False
    if not provided:
        return False
    return hmac.compare_digest(provided, configured)


def require_n8n_inbound_auth(request: Request) -> None:
    """FastAPI dependency that gates automation endpoints behind a shared secret.

    n8n sends the secret in the ``X-Automation-Secret`` header on every
    webhook call.  If the secret is not configured on the server side, the
    endpoint returns a 400 (not 401) to signal a server misconfiguration rather
    than a client credential error.

    Every outcome (accepted / rejected / misconfigured) is counted in the
    Prometheus counter ``itsm_n8n_machine_auth_total`` so ops can alert on
    unexpected rejection spikes.
    """
    endpoint = str(request.url.path or "").strip().lower() or "unknown"
    configured = settings.N8N_INBOUND_SECRET.strip()
    if not configured:
        # Server is misconfigured — warn loudly so it appears in logs.
        logger.warning("n8n inbound auth rejected: secret not configured path=%s", endpoint)
        n8n_machine_auth_total.labels(endpoint=endpoint, outcome="config_missing").inc()
        raise BadRequestError("n8n_inbound_secret_not_configured")

    provided = request.headers.get("X-Automation-Secret")
    if not _n8n_inbound_secret_matches(provided):
        logger.warning("n8n inbound auth rejected: invalid secret path=%s", endpoint)
        n8n_machine_auth_total.labels(endpoint=endpoint, outcome="rejected").inc()
        raise AuthenticationException(
            "invalid_automation_secret",
            error_code="INVALID_AUTOMATION_SECRET",
            status_code=401,
        )

    n8n_machine_auth_total.labels(endpoint=endpoint, outcome="accepted").inc()
    logger.info("n8n inbound auth accepted path=%s", endpoint)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the authenticated user from an incoming request.

    Token lookup order:
      1. ``Authorization: Bearer`` header (preferred for API clients).
      2. ``tw_access`` HttpOnly cookie (preferred for browser sessions).

    The JWT payload must have ``type == "access"`` to reject refresh tokens
    that were mistakenly sent to a non-refresh endpoint (token-type confusion
    attack mitigation).

    Raises:
        AuthenticationException: if no token is present, the token is invalid,
            or the user no longer exists in the database.
        ExpiredTokenError: if the token signature is valid but the ``exp`` claim
            has passed — the frontend catches this and triggers a silent refresh.
    """
    # Try Bearer header first; fall back to the HttpOnly session cookie.
    token = _extract_bearer_token(request) or request.cookies.get(settings.COOKIE_NAME)
    if not token:
        raise AuthenticationException(
            "not_authenticated",
            error_code="NOT_AUTHENTICATED",
            status_code=401,
        )

    try:
        payload = decode_token(token)
    except ValueError as exc:
        # decode_token raises ValueError("expired_token") for expired JWTs.
        if str(exc) == "expired_token":
            raise ExpiredTokenError("access_token_expired")
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )

    # Reject refresh tokens — they are only valid at POST /auth/refresh.
    token_type = payload.get("type")
    if token_type and token_type != ACCESS_TOKEN_TYPE:
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )

    # The "sub" claim holds the user's UUID (set at login time).
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )

    # Look up the user — if the account was deleted after the token was issued,
    # treat the token as invalid rather than returning a stale user object.
    user = db.get(User, user_id)
    if not user:
        raise AuthenticationException(
            "user_not_found",
            error_code="USER_NOT_FOUND",
            status_code=401,
        )

    return user


def require_role(required: str):
    """Dependency factory: allow only users with exactly ``required`` role string.

    Prefer ``require_roles()`` for new code — this variant does a string
    comparison against ``user.role.value`` and exists only for legacy callers.
    """
    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value != required:
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_roles(*required: UserRole):
    """Dependency factory: allow users whose role is in the ``required`` set.

    Example usage::

        @router.post("/admin-only")
        def endpoint(user = Depends(require_roles(UserRole.admin))):
            ...
    """
    allowed = set(required)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_permission(permission: str):
    """Dependency factory: allow users who have the named RBAC permission.

    Delegates to ``has_permission(user, permission)`` in ``app.core.rbac``.
    Permissions are fine-grained strings like ``"view_admin"`` or
    ``"edit_ticket_triage"`` — more granular than role checks alone.
    """
    def _checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Shorthand dependency that restricts an endpoint to admin-role users only."""
    if user.role != UserRole.admin:
        raise InsufficientPermissionsError("forbidden")
    return user
