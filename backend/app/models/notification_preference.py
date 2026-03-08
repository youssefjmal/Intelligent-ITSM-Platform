"""User-level notification preference model."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    email_min_severity: Mapped[str] = mapped_column(String(16), default="critical", nullable=False)
    digest_frequency: Mapped[str] = mapped_column(String(24), default="hourly", nullable=False)
    quiet_hours_start: Mapped[dt.time | None] = mapped_column(Time(timezone=False), nullable=True)
    quiet_hours_end: Mapped[dt.time | None] = mapped_column(Time(timezone=False), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

