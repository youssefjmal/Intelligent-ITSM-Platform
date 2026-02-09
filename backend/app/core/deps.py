"""Common FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthenticationException, InsufficientPermissionsError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        raise AuthenticationException(
            "not_authenticated",
            error_code="NOT_AUTHENTICATED",
            status_code=401,
        )

    try:
        payload = decode_token(token)
    except ValueError:
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


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.value != "admin":
        raise InsufficientPermissionsError("forbidden")
    return user
