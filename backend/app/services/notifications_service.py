"""Service helpers for notifications CRUD and read-state updates."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.notification import Notification


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def list_notifications(
    db: Session,
    *,
    user_id: UUID,
    unread_only: bool = False,
    limit: int = 20,
) -> list[Notification]:
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


def count_unread_notifications(db: Session, *, user_id: UUID) -> int:
    return db.query(Notification).filter(Notification.user_id == user_id, Notification.read_at.is_(None)).count()


def create_notification(
    db: Session,
    *,
    user_id: UUID,
    title: str,
    body: str | None = None,
    severity: str = "info",
    link: str | None = None,
    source: str | None = None,
) -> Notification:
    record = Notification(
        user_id=user_id,
        title=title,
        body=body,
        severity=severity,
        link=link,
        source=source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def mark_notification_as_read(
    db: Session,
    *,
    user_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    record = db.get(Notification, notification_id)
    if not record or record.user_id != user_id:
        return None
    if record.read_at is None:
        record.read_at = utcnow()
        db.commit()
        db.refresh(record)
    return record


def mark_all_notifications_as_read(db: Session, *, user_id: UUID) -> int:
    now = utcnow()
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()
    return int(updated or 0)

