"""Problem management model grouping recurring incidents."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ProblemStatus, TicketCategory


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[ProblemStatus] = mapped_column(
        Enum(ProblemStatus, name="problem_status", values_callable=lambda x: [e.value for e in x]),
        default=ProblemStatus.open,
        nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurrences_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    workaround: Mapped[str | None] = mapped_column(Text, nullable=True)
    permanent_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    tickets = relationship("Ticket", back_populates="problem")
