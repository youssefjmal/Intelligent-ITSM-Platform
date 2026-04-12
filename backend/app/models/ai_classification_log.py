"""Audit log for every AI classification decision made by the classifier."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AiClassificationLog(Base):
    __tablename__ = "ai_classification_logs"
    __table_args__ = (
        Index("ix_ai_classification_logs_ticket_id", "ticket_id"),
        Index("ix_ai_classification_logs_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Source context
    ticket_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    # "draft"    → called from POST /tickets/classify-draft (before creation)
    # "creation" → called automatically when a ticket is created
    # "manual"   → called from the AI suggest endpoint

    # Input
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # First 300 chars of description to keep the table lean

    # Output — what the model decided
    suggested_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    suggested_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suggested_ticket_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Confidence
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "high" | "medium" | "low"

    # How the decision was made
    decision_source: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    # "llm"       → LLM answered successfully
    # "semantic"  → semantic match was strong enough, LLM was skipped
    # "fallback"  → LLM failed, rule-based fallback used

    strong_match_count: Mapped[int | None] = mapped_column(nullable=True)
    recommendation_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Model version (ISO 42001 — traceability of which model produced the decision)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # ISO 42001 human oversight (clause 6.1 / 9.1)
    # Set when an admin or agent reviews and optionally overrides the AI decision.
    human_reviewed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
