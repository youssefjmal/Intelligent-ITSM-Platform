"""Recommendation model for AI insights stored in the database."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RecommendationImpact, RecommendationType


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    type: Mapped[RecommendationType] = mapped_column(
        Enum(RecommendationType, name="recommendation_type", values_callable=lambda x: [e.value for e in x])
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_tickets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    impact: Mapped[RecommendationImpact] = mapped_column(
        Enum(RecommendationImpact, name="recommendation_impact", values_callable=lambda x: [e.value for e in x]),
        default=RecommendationImpact.medium,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
