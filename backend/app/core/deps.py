"""Common FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthenticationException, ExpiredTokenError, InsufficientPermissionsError
from app.core.rbac import has_permission
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    cleaned = token.strip()
    return cleaned or None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
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
        if str(exc) == "expired_token":
            raise ExpiredTokenError("access_token_expired")
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )
    token_type = payload.get("type")
    if token_type and token_type != ACCESS_TOKEN_TYPE:
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(
            "invalid_token",
            error_code="INVALID_TOKEN",
            status_code=401,
        )

    user = db.get(User, user_id)
    if not user:
        raise AuthenticationException(
            "user_not_found",
            error_code="USER_NOT_FOUND",
            status_code=401,
        )

    return user


def require_role(required: str):
    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value != required:
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_roles(*required: UserRole):
    allowed = set(required)

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_permission(permission: str):
    def _checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise InsufficientPermissionsError("forbidden")
        return user

    return _checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise InsufficientPermissionsError("forbidden")
    return user
