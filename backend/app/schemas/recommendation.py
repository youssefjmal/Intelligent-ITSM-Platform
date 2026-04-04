"""Pydantic schemas for AI recommendations."""

from __future__ import annotations

import datetime as dt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import RecommendationImpact, RecommendationType
from app.schemas.ai import (
    AILLMGeneralAdvisory,
    AIRecommendationCurrentFeedback,
    AIRecommendationFeedbackSummary,
    AIRecommendationFeedbackSummaryWithBreakdown,
)


class RecommendationEvidenceOut(BaseModel):
    evidence_type: str
    reference: str
    excerpt: str | None = None
    source_id: str | None = None
    title: str | None = None
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    why_relevant: str | None = None


class RecommendationOut(BaseModel):
    id: str
    type: RecommendationType
    entity_type: str = "ticket"
    title: str
    description: str
    recommended_action: str | None = None
    reasoning: str | None = None
    related_tickets: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: str = "low"
    confidence_label: str = "low"
    impact: RecommendationImpact
    tentative: bool = False
    probable_root_cause: str | None = None
    root_cause: str | None = None
    supporting_context: str | None = None
    source_label: str = "fallback_rules"
    recommendation_mode: str = "fallback_rules"
    action_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filtered_weak_match: bool = False
    mode: str = "evidence_action"
    display_mode: str = "evidence_action"
    match_summary: str | None = None
    why_this_matches: list[str] = Field(default_factory=list)
    next_best_actions: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    base_recommended_action: str | None = None
    base_next_best_actions: list[str] = Field(default_factory=list)
    base_validation_steps: list[str] = Field(default_factory=list)
    action_refinement_source: str | None = None
    evidence_sources: list[RecommendationEvidenceOut] = Field(default_factory=list)
    llm_general_advisory: AILLMGeneralAdvisory | None = None
    current_feedback: AIRecommendationCurrentFeedback | None = None
    feedback_summary: AIRecommendationFeedbackSummary | None = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class SLAStrategiesOut(BaseModel):
    summary: str
    common_breach_patterns: list[str]
    process_improvements: list[str]
    confidence: float
    sources: list[str]


class RecommendationFeedbackSubmitRequest(BaseModel):
    ticket_id: str | None = Field(default=None, max_length=20)
    feedback_type: str = Field(min_length=1, max_length=24)
    recommended_action: str | None = None
    display_mode: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: str | None = None
    match_summary: str | None = None
    evidence_count: int | None = Field(default=None, ge=0, le=99)
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("feedback_type", mode="before")
    @classmethod
    def normalize_feedback_type(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split()).strip().lower()
        if cleaned not in {"useful", "not_relevant", "applied", "rejected"}:
            raise ValueError("invalid_feedback_type")
        return cleaned


class RecommendationFeedbackOut(BaseModel):
    status: str
    recommendation_id: str
    source_surface: str = "recommendations_page"
    current_feedback: AIRecommendationCurrentFeedback | None = None
    feedback_summary: AIRecommendationFeedbackSummary | None = None


class RecommendationFeedbackAnalyticsOut(AIRecommendationFeedbackSummaryWithBreakdown):
    source_surface: str | None = None
