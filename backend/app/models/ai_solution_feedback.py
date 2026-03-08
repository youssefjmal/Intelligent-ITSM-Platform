"""Human feedback events for AI solution recommendations."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AiSolutionFeedback(Base):
    __tablename__ = "ai_solution_feedback"
    __table_args__ = (
        Index("ix_ai_solution_feedback_source_source_id", "source", "source_id"),
        Index("ix_ai_solution_feedback_user_id", "user_id"),
        Index("ix_ai_solution_feedback_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vote: Mapped[str] = mapped_column(String(16), nullable=False)  # helpful | not_helpful
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

