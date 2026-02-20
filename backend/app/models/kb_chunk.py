"""Semantic KB chunk model (pgvector-backed)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class KBChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_content_hash", "content_hash"),
        Index(
            "uq_kb_chunks_jira_comment_identity",
            "source_type",
            "jira_key",
            "comment_id",
            unique=True,
            postgresql_where=text(
                "source_type = 'jira_comment' AND jira_key IS NOT NULL AND comment_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_kb_chunks_jira_issue_identity",
            "source_type",
            "jira_issue_id",
            unique=True,
            postgresql_where=text("source_type = 'jira_issue' AND jira_issue_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    jira_issue_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    jira_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
