"""Security helpers for hashing passwords and issuing JWTs."""

from __future__ import annotations

import datetime as dt
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def _create_token(data: dict[str, Any], *, expires_delta: dt.timedelta, token_type: str) -> str:
    to_encode = data.copy()
    now = dt.datetime.now(dt.timezone.utc)
    expire = now + expires_delta
    to_encode.update({"type": token_type, "iat": int(now.timestamp()), "exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(data: dict[str, Any], expires_minutes: int | None = None) -> str:
    return _create_token(
        data,
        expires_delta=dt.timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type=ACCESS_TOKEN_TYPE,
    )


def create_refresh_token(data: dict[str, Any], expires_days: int | None = None) -> str:
    return _create_token(
        data,
        expires_delta=dt.timedelta(days=expires_days or settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type=REFRESH_TOKEN_TYPE,
    )


def decode_token(token: str, *, verify_exp: bool = True) -> dict[str, Any]:
    options = {"verify_exp": verify_exp}
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options=options,
        )
    except ExpiredSignatureError as exc:
        raise ValueError("expired_token") from exc
    except JWTError as exc:
        raise ValueError("invalid_token") from exc
