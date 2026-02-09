"""Service helpers for user registration, login, and email verification."""

from __future__ import annotations

import datetime as dt
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.verification_token import VerificationToken
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


def create_user(db: Session, data: UserCreate) -> User:
    user = User(
        id=uuid4(),
        email=data.email.lower(),
        name=data.name.strip(),
        role=data.role,
        password_hash=hash_password(data.password),
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User created: %s", user.email)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not user.password_hash:
        logger.warning("Login failed: user not found (%s)", email)
        return None
    if not verify_password(password, user.password_hash):
        logger.warning("Login failed: invalid password (%s)", email)
        return None
    logger.info("User authenticated: %s", user.email)
    return user


def create_verification_token(db: Session, user: User) -> VerificationToken:
    now = dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS)
    token = VerificationToken(user_id=user.id, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info("Verification token issued: %s", user.email)
    return token


def verify_email_token(db: Session, token_str: str) -> User | None:
    token = db.get(VerificationToken, token_str)
    if not token or token.used_at is not None:
        logger.warning("Email verification failed: invalid or used token")
        return None
    if token.expires_at < dt.datetime.now(dt.timezone.utc):
        logger.warning("Email verification failed: expired token")
        return None

    user = db.get(User, token.user_id)
    if not user:
        logger.warning("Email verification failed: user not found")
        return None

    user.is_verified = True
    token.used_at = dt.datetime.now(dt.timezone.utc)
    db.add(user)
    db.add(token)
    db.commit()
    db.refresh(user)
    logger.info("Email verified: %s", user.email)
    return user
