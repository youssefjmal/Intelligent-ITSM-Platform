"""User model for authentication and authorization."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SeniorityLevel, UserRole


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        default=UserRole.viewer,
    )
    specializations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    seniority_level: Mapped[SeniorityLevel] = mapped_column(
        Enum(SeniorityLevel, name="user_seniority", values_callable=lambda x: [e.value for e in x]),
        default=SeniorityLevel.middle,
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_tickets: Mapped[int] = mapped_column(Integer, default=10)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
