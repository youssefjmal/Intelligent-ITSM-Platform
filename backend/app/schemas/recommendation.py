"""Pydantic schemas for AI recommendations."""

from __future__ import annotations

import datetime as dt
from pydantic import BaseModel

from app.models.enums import RecommendationImpact, RecommendationType


class RecommendationOut(BaseModel):
    id: str
    type: RecommendationType
    title: str
    description: str
    related_tickets: list[str]
    confidence: int
    impact: RecommendationImpact
    created_at: dt.datetime

    class Config:
        from_attributes = True
