"""Persistence and aggregation for AI recommendation feedback."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.ai_solution_feedback import AiSolutionFeedback


def record_feedback(
    db: Session,
    *,
    user_id,
    query: str | None,
    recommendation_text: str,
    source: str,
    source_id: str | None,
    vote: str,
    context: dict[str, Any] | None,
) -> AiSolutionFeedback:
    row = AiSolutionFeedback(
        user_id=user_id,
        query=query,
        recommendation_text=recommendation_text,
        source=source,
        source_id=source_id,
        vote=vote,
        context_json=context,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def aggregate_feedback_counts(
    db: Session,
    *,
    source: str,
    source_id: str | None,
) -> dict[str, int]:
    query = select(
        func.sum(case((AiSolutionFeedback.vote == "helpful", 1), else_=0)).label("helpful"),
        func.sum(case((AiSolutionFeedback.vote == "not_helpful", 1), else_=0)).label("not_helpful"),
    ).where(AiSolutionFeedback.source == source)
    if source_id:
        query = query.where(AiSolutionFeedback.source_id == source_id)
    row = db.execute(query).one()
    return {
        "helpful": int(row.helpful or 0),
        "not_helpful": int(row.not_helpful or 0),
    }


def aggregate_feedback_for_sources(
    db: Session,
    *,
    source: str,
    source_ids: list[str],
) -> dict[str, dict[str, int]]:
    normalized = [item.strip() for item in source_ids if item and item.strip()]
    if not normalized:
        return {}
    rows = db.execute(
        select(
            AiSolutionFeedback.source_id,
            func.sum(case((AiSolutionFeedback.vote == "helpful", 1), else_=0)).label("helpful"),
            func.sum(case((AiSolutionFeedback.vote == "not_helpful", 1), else_=0)).label("not_helpful"),
        )
        .where(
            AiSolutionFeedback.source == source,
            AiSolutionFeedback.source_id.in_(normalized),
        )
        .group_by(AiSolutionFeedback.source_id)
    ).all()
    return {
        str(source_id): {"helpful": int(helpful or 0), "not_helpful": int(not_helpful or 0)}
        for source_id, helpful, not_helpful in rows
        if source_id
    }

