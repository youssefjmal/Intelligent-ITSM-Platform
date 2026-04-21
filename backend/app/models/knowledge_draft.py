"""KnowledgeDraft — persisted AI-generated knowledge base draft from a resolved ticket."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Float, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class KnowledgeDraft(Base):
    __tablename__ = "knowledge_drafts"
    __table_args__ = (
        Index("ix_knowledge_drafts_ticket_id", "ticket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    symptoms: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    workaround: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_steps: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="llm")
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    jira_issue_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Full browser URL of the Confluence page created on publish (null until published via Confluence).
    confluence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
