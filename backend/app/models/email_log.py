"""Email log model for recorded verification and welcome emails."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import EmailKind


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    to: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[EmailKind] = mapped_column(
        Enum(EmailKind, name="email_kind", values_callable=lambda x: [e.value for e in x]),
        default=EmailKind.verification,
    )
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
