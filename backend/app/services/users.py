"""Service helpers for admin user management."""

from __future__ import annotations

from uuid import UUID
import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.enums import UserRole

logger = logging.getLogger(__name__)


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def update_role(db: Session, user_id: str, role: UserRole) -> User | None:
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return None
    user = db.get(User, user_uuid)
    if not user:
        logger.warning("User role update failed (not found): %s", user_id)
        return None
    user.role = role
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User role updated: %s -> %s", user.email, role.value)
    return user


def delete_user(db: Session, user_id: str) -> bool:
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return False
    user = db.get(User, user_uuid)
    if not user:
        logger.warning("User delete failed (not found): %s", user_id)
        return False
    db.delete(user)
    db.commit()
    logger.info("User deleted: %s", user.email)
    return True


def list_assignees(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.role.in_([UserRole.admin, UserRole.agent]))
        .order_by(User.name.asc())
        .all()
    )
