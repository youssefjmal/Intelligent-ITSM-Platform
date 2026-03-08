"""Notification delivery tracing events for debug and observability."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class NotificationDeliveryEvent(Base):
    __tablename__ = "notification_delivery_events"
    __table_args__ = (
        Index("ix_notification_delivery_events_notification_id", "notification_id"),
        Index("ix_notification_delivery_events_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notification_id: Mapped[UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    workflow_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipients_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    duplicate_suppression: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False, default="in-app")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

