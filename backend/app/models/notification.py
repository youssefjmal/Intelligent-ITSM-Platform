"""Notification model for user-facing in-app alerts."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_read_at", "user_id", "read_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
