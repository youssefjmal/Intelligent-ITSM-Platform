"""Service helpers for user registration, login, and email verification."""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.models.enums import UserRole
from app.models.password_reset_token import PasswordResetToken
from app.models.verification_token import VerificationToken
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    user: User


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _refresh_expiry() -> dt.datetime:
    return _utcnow() + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def _build_claims(user: User) -> dict[str, str]:
    return {"sub": str(user.id), "role": user.role.value}


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


def build_default_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0].strip()
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", local_part).strip()
    if not cleaned:
        return "New User"

    formatted = " ".join(piece.capitalize() for piece in cleaned.split() if piece)
    if not formatted:
        return "New User"
    if len(formatted) == 1:
        return f"User {formatted.upper()}"
    return formatted[:80]


def issue_auth_tokens(db: Session, user: User) -> AuthTokens:
    refresh_jti = str(uuid4())
    refresh_expires_at = _refresh_expiry()
    access_jti = str(uuid4())

    access_token = create_access_token(
        {
            **_build_claims(user),
            "jti": access_jti,
        }
    )
    refresh_token = create_refresh_token(
        {
            **_build_claims(user),
            "jti": refresh_jti,
        },
    )

    db.add(
        RefreshToken(
            jti=refresh_jti,
            user_id=user.id,
            expires_at=refresh_expires_at,
        )
    )
    db.commit()
    return AuthTokens(access_token=access_token, refresh_token=refresh_token, user=user)


def revoke_refresh_token(db: Session, refresh_token: str) -> bool:
    try:
        payload = decode_token(refresh_token, verify_exp=False)
    except ValueError:
        return False

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        return False

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        return False
    try:
        parsed_user_id = UUID(str(user_id))
    except ValueError:
        return False

    session_token = db.get(RefreshToken, jti)
    if not session_token or session_token.user_id != parsed_user_id:
        return False
    if session_token.revoked_at is not None:
        return True

    session_token.revoked_at = _utcnow()
    db.add(session_token)
    db.commit()
    return True


def revoke_all_refresh_tokens_for_user(db: Session, user: User) -> None:
    now = _utcnow()
    (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    db.commit()


def rotate_refresh_token(db: Session, refresh_token: str) -> AuthTokens:
    payload = decode_token(refresh_token)
    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise ValueError("invalid_token")

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise ValueError("invalid_token")
    try:
        parsed_user_id = UUID(str(user_id))
    except ValueError:
        raise ValueError("invalid_token")

    session_token = db.get(RefreshToken, jti)
    if not session_token or session_token.user_id != parsed_user_id:
        raise ValueError("invalid_token")
    if session_token.revoked_at is not None:
        raise ValueError("invalid_token")

    now = _utcnow()
    if session_token.expires_at <= now:
        session_token.revoked_at = now
        db.add(session_token)
        db.commit()
        raise ValueError("expired_token")

    user = db.get(User, parsed_user_id)
    if not user:
        raise ValueError("invalid_token")

    new_refresh_jti = str(uuid4())
    new_refresh_expires_at = _refresh_expiry()
    new_access_jti = str(uuid4())
    access_token = create_access_token(
        {
            **_build_claims(user),
            "jti": new_access_jti,
        }
    )
    new_refresh_token = create_refresh_token(
        {
            **_build_claims(user),
            "jti": new_refresh_jti,
        },
    )

    session_token.revoked_at = now
    session_token.replaced_by_jti = new_refresh_jti
    db.add(session_token)
    db.add(
        RefreshToken(
            jti=new_refresh_jti,
            user_id=user.id,
            expires_at=new_refresh_expires_at,
        )
    )
    db.commit()
    return AuthTokens(access_token=access_token, refresh_token=new_refresh_token, user=user)


def create_user(db: Session, data: UserCreate) -> User:
    user = User(
        id=uuid4(),
        email=data.email.lower(),
        name=data.name.strip(),
        role=UserRole.user,
        specializations=data.specializations or [],
        password_hash=hash_password(data.password),
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User created: %s", user.email)
    return user


def create_user_from_email_password(db: Session, email: str, password: str) -> User:
    payload = UserCreate(
        email=email,
        password=password,
        name=build_default_name_from_email(email),
        specializations=[],
    )
    return create_user(db, payload)


def create_or_update_user_from_google(
    db: Session,
    *,
    google_id: str,
    email: str,
    name: str | None,
    email_verified: bool,
) -> User:
    normalized_email = email.lower().strip()
    if not normalized_email:
        raise ValueError("google_email_missing")
    if not google_id.strip():
        raise ValueError("google_sub_missing")

    existing_google_user = db.query(User).filter(User.google_id == google_id).first()
    if existing_google_user:
        if email_verified:
            existing_google_user.is_verified = True
        if normalized_email and existing_google_user.email != normalized_email:
            conflicting_user = find_user_by_email(db, normalized_email)
            if conflicting_user and conflicting_user.id != existing_google_user.id:
                raise ValueError("google_email_conflict")
            existing_google_user.email = normalized_email
        clean_name = (name or "").strip()
        if clean_name:
            existing_google_user.name = clean_name[:255]
        db.add(existing_google_user)
        db.commit()
        db.refresh(existing_google_user)
        return existing_google_user

    email_user = find_user_by_email(db, normalized_email)
    if email_user:
        if email_user.google_id and email_user.google_id != google_id:
            raise ValueError("google_id_conflict")
        email_user.google_id = google_id
        if email_verified:
            email_user.is_verified = True
        clean_name = (name or "").strip()
        if clean_name and not email_user.name:
            email_user.name = clean_name[:255]
        db.add(email_user)
        db.commit()
        db.refresh(email_user)
        return email_user

    default_name = (name or "").strip() or build_default_name_from_email(normalized_email)
    user = User(
        id=uuid4(),
        email=normalized_email,
        name=default_name[:255],
        role=UserRole.user,
        specializations=[],
        password_hash=None,
        google_id=google_id,
        is_verified=bool(email_verified),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Google user created: %s", user.email)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = find_user_by_email(db, email)
    if not user or not user.password_hash:
        logger.warning("Login failed: user not found (%s)", email)
        return None
    if not verify_password(password, user.password_hash):
        logger.warning("Login failed: invalid password (%s)", email)
        return None
    logger.info("User authenticated: %s", user.email)
    return user


def create_verification_token(db: Session, user: User) -> VerificationToken:
    now = _utcnow()
    expires_at = now + dt.timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS)
    (
        db.query(VerificationToken)
        .filter(VerificationToken.user_id == user.id, VerificationToken.used_at.is_(None))
        .update({VerificationToken.used_at: now}, synchronize_session=False)
    )
    token = VerificationToken(user_id=user.id, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info("Verification token issued: %s", user.email)
    return token


def _mark_user_verified(db: Session, user: User, matched_token: VerificationToken) -> User:
    now = _utcnow()
    user.is_verified = True
    (
        db.query(VerificationToken)
        .filter(VerificationToken.user_id == user.id, VerificationToken.used_at.is_(None))
        .update({VerificationToken.used_at: now}, synchronize_session=False)
    )
    matched_token.used_at = now
    db.add(user)
    db.add(matched_token)
    db.commit()
    db.refresh(user)
    logger.info("Email verified: %s", user.email)
    return user


def verify_email_token(db: Session, token_str: str) -> User | None:
    token = db.get(VerificationToken, token_str)
    if not token or token.used_at is not None:
        logger.warning("Email verification failed: invalid or used token")
        return None
    if token.expires_at < _utcnow():
        logger.warning("Email verification failed: expired token")
        return None

    user = db.get(User, token.user_id)
    if not user:
        logger.warning("Email verification failed: user not found")
        return None

    return _mark_user_verified(db, user, token)


def verify_email_code(db: Session, email: str, code: str) -> User | None:
    now = _utcnow()
    token = (
        db.query(VerificationToken)
        .join(User, VerificationToken.user_id == User.id)
        .filter(
            User.email == email.lower(),
            VerificationToken.code == code,
            VerificationToken.used_at.is_(None),
            VerificationToken.expires_at >= now,
        )
        .order_by(VerificationToken.created_at.desc())
        .first()
    )
    if not token:
        logger.warning("Email verification failed: invalid or expired code (%s)", email.lower())
        return None

    user = db.get(User, token.user_id)
    if not user:
        logger.warning("Email verification failed: user not found for code")
        return None

    return _mark_user_verified(db, user, token)


def create_password_reset_token(db: Session, user: User) -> PasswordResetToken:
    now = _utcnow()
    expires_at = now + dt.timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
    token = PasswordResetToken(user_id=user.id, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info("Password reset token issued: %s", user.email)
    return token


def reset_password_with_token(db: Session, token_str: str, new_password: str) -> User | None:
    token = db.get(PasswordResetToken, token_str)
    if not token or token.used_at is not None:
        logger.warning("Password reset failed: invalid or used token")
        return None
    if token.expires_at < _utcnow():
        logger.warning("Password reset failed: expired token")
        return None

    user = db.get(User, token.user_id)
    if not user:
        logger.warning("Password reset failed: user not found")
        return None

    now = _utcnow()
    user.password_hash = hash_password(new_password)
    user.is_verified = True
    token.used_at = now
    (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    db.add(user)
    db.add(token)
    db.commit()
    db.refresh(user)
    logger.info("Password reset success: %s", user.email)
    return user
