"""Audit trail for automated SLA/AI actions."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    __table_args__ = (
        Index("ix_automation_events_ticket_id", "ticket_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
