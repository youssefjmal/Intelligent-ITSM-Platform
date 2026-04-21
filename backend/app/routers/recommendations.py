"""Recommendation endpoints backed by the database."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.core import cache as _cache
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

from app.schemas.recommendation import (
    RecommendationFeedbackAnalyticsOut,
    RecommendationFeedbackOut,
    RecommendationFeedbackSubmitRequest,
    RecommendationOut,
    SLAStrategiesOut,
)
from app.services.ai.feedback import (
    aggregate_agent_feedback_analytics,
    get_feedback_bundle_for_target,
    upsert_agent_feedback,
)
from app.services.recommendations import build_sla_strategies, list_recommendations

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])


@router.get("/", response_model=list[RecommendationOut])
def get_recommendations(
    locale: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecommendationOut]:
    import time as _time
    key = _cache.make_key("recommendations", str(current_user.id), {"locale": str(locale or "")})
    hit = _cache.get(key)
    if hit is not None:
        logger.info("recommendations CACHE HIT key=%s items=%d", key, len(hit))
        return [RecommendationOut.model_validate(item) for item in hit]
    logger.info("recommendations CACHE MISS key=%s — running full pipeline", key)
    t0 = _time.perf_counter()
    records = list_recommendations(db, current_user, locale=locale)
    result = [RecommendationOut.model_validate(r) for r in records]
    elapsed = _time.perf_counter() - t0
    stored = _cache.set(key, [r.model_dump() for r in result], ttl=settings.CACHE_TTL_RECOMMENDATIONS)
    logger.info("recommendations built in %.2fs — cache_stored=%s items=%d", elapsed, stored, len(result))
    return result


@router.get("/sla-strategies", response_model=SLAStrategiesOut)
def get_sla_strategies(
    locale: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SLAStrategiesOut:
    key = _cache.make_key("sla_strategies", str(current_user.id), {"locale": str(locale or "")})
    hit = _cache.get(key)
    if hit is not None:
        return SLAStrategiesOut(**hit)
    payload = build_sla_strategies(db, user=current_user, locale=locale)
    _cache.set(key, payload, ttl=settings.CACHE_TTL_SLA_STRATEGIES)
    return SLAStrategiesOut(**payload)


@router.get("/feedback-analytics", response_model=RecommendationFeedbackAnalyticsOut)
def get_feedback_analytics(
    source_surface: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
) -> RecommendationFeedbackAnalyticsOut:
    payload = aggregate_agent_feedback_analytics(db, source_surface=source_surface)
    return RecommendationFeedbackAnalyticsOut(**payload, source_surface=source_surface)


@router.get("/{recommendation_id}/feedback", response_model=RecommendationFeedbackOut)
def get_recommendation_feedback(
    recommendation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationFeedbackOut:
    bundle = get_feedback_bundle_for_target(
        db,
        current_user_id=getattr(current_user, "id", None),
        source_surface="recommendations_page",
        recommendation_id=recommendation_id,
    )
    return RecommendationFeedbackOut(
        status="ok",
        recommendation_id=recommendation_id,
        current_feedback=bundle.get("current_feedback"),
        feedback_summary=bundle.get("feedback_summary"),
    )


@router.post("/{recommendation_id}/feedback", response_model=RecommendationFeedbackOut)
def submit_recommendation_feedback(
    recommendation_id: str,
    payload: RecommendationFeedbackSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationFeedbackOut:
    upsert_agent_feedback(
        db,
        user_id=getattr(current_user, "id", None),
        feedback_type=payload.feedback_type,
        source_surface="recommendations_page",
        ticket_id=payload.ticket_id,
        recommendation_id=recommendation_id,
        recommended_action=payload.recommended_action,
        display_mode=payload.display_mode,
        confidence=payload.confidence,
        reasoning=payload.reasoning,
        match_summary=payload.match_summary,
        evidence_count=payload.evidence_count,
        metadata=payload.metadata,
    )
    # Invalidate recommendations cache so next GET reflects updated feedback state
    _cache.delete_pattern(f"itsm:recommendations:{current_user.id}:*")
    _cache.delete(f"itsm:recommendations:{current_user.id}")
    bundle = get_feedback_bundle_for_target(
        db,
        current_user_id=getattr(current_user, "id", None),
        source_surface="recommendations_page",
        recommendation_id=recommendation_id,
    )
    return RecommendationFeedbackOut(
        status="recorded",
        recommendation_id=recommendation_id,
        current_feedback=bundle.get("current_feedback"),
        feedback_summary=bundle.get("feedback_summary"),
    )


@router.get("/analytics")
def get_recommendation_analytics(
    period_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.role.value not in ("admin", "agent"):
        from app.core.exceptions import InsufficientPermissionsError

        raise InsufficientPermissionsError("forbidden")
    payload = aggregate_agent_feedback_analytics(db)
    return {
        "period_days": period_days,
        "useful_rate": payload.get("usefulness_rate", 0.0),
        **payload,
    }
