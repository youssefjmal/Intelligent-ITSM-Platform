"""AI SLA risk scoring audit records (shadow/assist modes)."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AiSlaRiskEvaluation(Base):
    __tablename__ = "ai_sla_risk_evaluations"
    __table_args__ = (
        Index("ix_ai_sla_risk_evaluations_ticket_id", "ticket_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    suggested_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(16), nullable=False, default="shadow")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
