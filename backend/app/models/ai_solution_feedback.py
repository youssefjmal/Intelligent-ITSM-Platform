"""Human feedback events for AI recommendation outputs."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
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
        Index("ix_ai_solution_feedback_target_lookup", "user_id", "source_surface", "target_key"),
        Index("ix_ai_solution_feedback_ticket_surface", "ticket_id", "source_surface"),
        Index("ix_ai_solution_feedback_recommendation_surface", "recommendation_id", "source_surface"),
        Index("ix_ai_solution_feedback_feedback_type", "feedback_type"),
        # Index added in migration 0032 to support legacy analytics queries on the
        # deprecated `vote` column without full-table scans.  Remove together with
        # the column when `vote` is formally retired.
        Index("ix_ai_solution_feedback_vote", "vote"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Deprecated: use feedback_type instead.  vote stores legacy values
    # ("helpful" | "not_helpful") from before the agent feedback types were
    # introduced.  Retained for query compatibility with existing analytics.
    # Removal condition: remove after all analytics queries are migrated to
    # use feedback_type and the ix_ai_solution_feedback_vote index is dropped.
    vote: Mapped[str] = mapped_column(String(16), nullable=False)
    feedback_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_surface: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recommended_action_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_mode_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_summary_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_count_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        onupdate=utcnow,
    )
