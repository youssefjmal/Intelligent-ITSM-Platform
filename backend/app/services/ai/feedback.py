"""Persistence and aggregation helpers for AI recommendation feedback."""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.ai_solution_feedback import AiSolutionFeedback
from app.services.ai.calibration import confidence_band

logger = logging.getLogger(__name__)

LEGACY_FEEDBACK_TYPES = {"helpful", "not_helpful"}
AGENT_FEEDBACK_TYPES = {"useful", "not_relevant", "applied", "rejected"}
AGENT_FEEDBACK_SURFACES = {"ticket_detail", "recommendations_page", "ticket_chatbot"}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_line(value: Any) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned or None


def _normalize_feedback_type(value: str | None) -> str | None:
    cleaned = _normalize_line(value)
    return cleaned.lower() if cleaned else None


def _safe_rollback(db: Session | None) -> None:
    if db is None:
        return
    rollback = getattr(db, "rollback", None)
    if not callable(rollback):
        return
    try:
        rollback()
    except Exception:  # noqa: BLE001
        logger.debug("Feedback rollback cleanup failed.", exc_info=True)


def _target_key(
    *,
    source_surface: str,
    ticket_id: str | None = None,
    recommendation_id: str | None = None,
    answer_type: str | None = None,
) -> str | None:
    if source_surface == "ticket_detail" and ticket_id:
        return f"ticket:{ticket_id}"
    if source_surface == "ticket_chatbot" and ticket_id and answer_type:
        return f"ticket_chatbot:{ticket_id}:{answer_type}"
    if source_surface == "recommendations_page" and recommendation_id:
        return f"recommendation:{recommendation_id}"
    return None


def _feedback_state_from_row(row: AiSolutionFeedback | None) -> dict[str, Any] | None:
    if not row or not row.feedback_type:
        return None
    return {
        "feedback_type": row.feedback_type,
        "created_at": row.created_at,
        "updated_at": row.updated_at or row.created_at,
    }


def _empty_feedback_summary() -> dict[str, Any]:
    return {
        "total_feedback": 0,
        "useful_count": 0,
        "not_relevant_count": 0,
        "applied_count": 0,
        "rejected_count": 0,
        "usefulness_rate": 0.0,
        "applied_rate": 0.0,
        "rejection_rate": 0.0,
    }


def _summarize_feedback_rows(
    rows: list[AiSolutionFeedback],
    *,
    current_user_id=None,
) -> dict[str, Any]:
    relevant = [row for row in rows if row.feedback_type in AGENT_FEEDBACK_TYPES]
    if not relevant:
        return {
            "current_feedback": None,
            "feedback_summary": _empty_feedback_summary(),
        }

    counts = Counter(str(row.feedback_type) for row in relevant)
    total = sum(counts.values())
    latest_for_user = None
    if current_user_id is not None:
        user_rows = [row for row in relevant if row.user_id == current_user_id]
        if user_rows:
            latest_for_user = max(
                user_rows,
                key=lambda item: item.updated_at or item.created_at or _utcnow(),
            )

    return {
        "current_feedback": _feedback_state_from_row(latest_for_user),
        "feedback_summary": {
            "total_feedback": total,
            "useful_count": int(counts.get("useful", 0)),
            "not_relevant_count": int(counts.get("not_relevant", 0)),
            "applied_count": int(counts.get("applied", 0)),
            "rejected_count": int(counts.get("rejected", 0)),
            "usefulness_rate": round(int(counts.get("useful", 0)) / total, 4) if total else 0.0,
            "applied_rate": round(int(counts.get("applied", 0)) / total, 4) if total else 0.0,
            "rejection_rate": round(int(counts.get("rejected", 0)) / total, 4) if total else 0.0,
        },
    }


def _summary_only(rows: list[AiSolutionFeedback]) -> dict[str, Any]:
    return _summarize_feedback_rows(rows)["feedback_summary"]


def _confidence_band_from_row(row: AiSolutionFeedback) -> str:
    metadata = row.context_json if isinstance(row.context_json, dict) else {}
    explicit = _normalize_feedback_type(str(metadata.get("confidence_band") or ""))
    if explicit in {"low", "medium", "high"}:
        return explicit
    value = row.confidence_snapshot
    if value is None:
        return "unknown"
    return confidence_band(value)


def _breakdown_summary(
    rows: list[AiSolutionFeedback],
    *,
    labeler,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[AiSolutionFeedback]] = defaultdict(list)
    for row in rows:
        label = _normalize_feedback_type(labeler(row)) or "unknown"
        grouped[label].append(row)
    return {
        label: _summary_only(group_rows)
        for label, group_rows in grouped.items()
    }


def _find_existing_agent_feedback(
    db: Session,
    *,
    user_id,
    source_surface: str,
    target_key: str,
) -> AiSolutionFeedback | None:
    return (
        db.query(AiSolutionFeedback)
        .filter(
            AiSolutionFeedback.user_id == user_id,
            AiSolutionFeedback.source_surface == source_surface,
            AiSolutionFeedback.target_key == target_key,
        )
        .order_by(AiSolutionFeedback.updated_at.desc(), AiSolutionFeedback.created_at.desc())
        .first()
    )


def _apply_agent_feedback_snapshot(
    row: AiSolutionFeedback,
    *,
    feedback_type: str,
    source_surface: str,
    ticket_id: str | None,
    recommendation_id: str | None,
    answer_type: str | None,
    recommended_action: str | None,
    display_mode: str | None,
    confidence: float | None,
    reasoning: str | None,
    match_summary: str | None,
    evidence_count: int | None,
    metadata: dict[str, Any] | None,
) -> AiSolutionFeedback:
    target_key = _target_key(
        source_surface=source_surface,
        ticket_id=ticket_id,
        recommendation_id=recommendation_id,
        answer_type=answer_type,
    )
    recommendation_text = _normalize_line(recommended_action) or _normalize_line(reasoning) or "feedback-captured"
    row.ticket_id = ticket_id
    row.recommendation_id = recommendation_id
    row.recommendation_text = recommendation_text
    row.source = source_surface
    row.source_id = recommendation_id or answer_type or ticket_id
    row.vote = feedback_type
    row.feedback_type = feedback_type
    row.source_surface = source_surface
    row.target_key = target_key
    row.recommended_action_snapshot = _normalize_line(recommended_action)
    row.display_mode_snapshot = _normalize_line(display_mode)
    row.confidence_snapshot = max(0.0, min(1.0, float(confidence))) if confidence is not None else None
    row.reasoning_snapshot = _normalize_line(reasoning)
    row.match_summary_snapshot = _normalize_line(match_summary)
    row.evidence_count_snapshot = max(0, int(evidence_count)) if evidence_count is not None else None
    row.context_json = dict(metadata or {}) or None
    row.updated_at = _utcnow()
    return row


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
    normalized_source = _normalize_line(source) or "unknown"
    normalized_source_id = _normalize_line(source_id)
    normalized_vote = _normalize_feedback_type(vote) or "helpful"
    row = AiSolutionFeedback(
        user_id=user_id,
        query=query,
        recommendation_text=recommendation_text,
        source=normalized_source,
        source_id=normalized_source_id,
        vote=normalized_vote,
        feedback_type=normalized_vote,
        source_surface="ticket_chatbot",
        target_key=f"chat:{normalized_source}:{normalized_source_id or 'inline'}",
        recommended_action_snapshot=_normalize_line(recommendation_text),
        reasoning_snapshot=_normalize_line(query),
        context_json=context,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:  # noqa: BLE001
        _safe_rollback(db)
        raise
    return row


def upsert_agent_feedback(
    db: Session,
    *,
    user_id,
    feedback_type: str,
    source_surface: str,
    ticket_id: str | None = None,
    recommendation_id: str | None = None,
    answer_type: str | None = None,
    recommended_action: str | None = None,
    display_mode: str | None = None,
    confidence: float | None = None,
    reasoning: str | None = None,
    match_summary: str | None = None,
    evidence_count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AiSolutionFeedback:
    normalized_type = _normalize_feedback_type(feedback_type)
    normalized_surface = _normalize_feedback_type(source_surface)
    normalized_answer_type = _normalize_feedback_type(answer_type)
    if normalized_type not in AGENT_FEEDBACK_TYPES:
        raise ValueError("invalid_feedback_type")
    if normalized_surface not in AGENT_FEEDBACK_SURFACES:
        raise ValueError("invalid_source_surface")
    if normalized_surface == "ticket_chatbot" and normalized_answer_type not in {
        "resolution_advice",
        "cause_analysis",
        "suggestion_resolution_advice",
    }:
        raise ValueError("invalid_chatbot_answer_type")

    normalized_ticket_id = _normalize_line(ticket_id)
    normalized_recommendation_id = _normalize_line(recommendation_id)
    target_key = _target_key(
        source_surface=normalized_surface,
        ticket_id=normalized_ticket_id,
        recommendation_id=normalized_recommendation_id,
        answer_type=normalized_answer_type,
    )
    if not target_key:
        raise ValueError("missing_feedback_target")

    existing = None
    if user_id is not None:
        existing = _find_existing_agent_feedback(
            db,
            user_id=user_id,
            source_surface=normalized_surface,
            target_key=target_key,
        )

    row = existing or AiSolutionFeedback(
        user_id=user_id,
        query=None,
        recommendation_text="feedback-captured",
        source=normalized_surface,
        source_id=normalized_recommendation_id or normalized_ticket_id,
        vote=normalized_type,
    )
    _apply_agent_feedback_snapshot(
        row,
        feedback_type=normalized_type,
        source_surface=normalized_surface,
        ticket_id=normalized_ticket_id,
        recommendation_id=normalized_recommendation_id,
        answer_type=normalized_answer_type,
        recommended_action=recommended_action,
        display_mode=display_mode,
        confidence=confidence,
        reasoning=reasoning,
        match_summary=match_summary,
        evidence_count=evidence_count,
        metadata=metadata,
    )
    try:
        if existing is None:
            db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:  # noqa: BLE001
        _safe_rollback(db)
        raise
    return row


def aggregate_feedback_counts(
    db: Session,
    *,
    source: str,
    source_id: str | None,
) -> dict[str, int]:
    normalized_source = _normalize_line(source)
    normalized_source_id = _normalize_line(source_id)
    if not normalized_source:
        return {"helpful": 0, "not_helpful": 0}
    try:
        query = db.query(AiSolutionFeedback).filter(AiSolutionFeedback.source == normalized_source)
        if normalized_source_id:
            query = query.filter(AiSolutionFeedback.source_id == normalized_source_id)
        rows = query.all()
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.warning("Legacy AI feedback counts unavailable: %s", exc)
        return {"helpful": 0, "not_helpful": 0}
    counts = Counter(str(row.vote) for row in rows if row.vote in LEGACY_FEEDBACK_TYPES)
    return {
        "helpful": int(counts.get("helpful", 0)),
        "not_helpful": int(counts.get("not_helpful", 0)),
    }


def aggregate_feedback_for_sources(
    db: Session,
    *,
    source: str,
    source_ids: list[str],
) -> dict[str, dict[str, int]]:
    normalized_source = _normalize_line(source)
    normalized_ids = [item.strip() for item in source_ids if item and item.strip()]
    if not normalized_source or not normalized_ids:
        return {}
    try:
        rows = (
            db.query(AiSolutionFeedback)
            .filter(
                AiSolutionFeedback.source == normalized_source,
                AiSolutionFeedback.source_id.in_(normalized_ids),
            )
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.warning("AI feedback source aggregation unavailable: %s", exc)
        return {}
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.source_id and row.vote in LEGACY_FEEDBACK_TYPES:
            grouped[str(row.source_id)][str(row.vote)] += 1
    return {
        source_id: {
            "helpful": int(counter.get("helpful", 0)),
            "not_helpful": int(counter.get("not_helpful", 0)),
        }
        for source_id, counter in grouped.items()
    }


def get_feedback_bundle_for_target(
    db: Session,
    *,
    current_user_id,
    source_surface: str,
    ticket_id: str | None = None,
    recommendation_id: str | None = None,
    answer_type: str | None = None,
) -> dict[str, Any]:
    normalized_surface = _normalize_feedback_type(source_surface)
    normalized_answer_type = _normalize_feedback_type(answer_type)
    try:
        query = db.query(AiSolutionFeedback).filter(AiSolutionFeedback.source_surface == normalized_surface)
        if normalized_surface in {"ticket_detail", "ticket_chatbot"} and ticket_id:
            if normalized_surface == "ticket_chatbot":
                target_key = _target_key(
                    source_surface=normalized_surface,
                    ticket_id=_normalize_line(ticket_id),
                    answer_type=normalized_answer_type,
                )
                if not target_key:
                    return {
                        "current_feedback": None,
                        "feedback_summary": _empty_feedback_summary(),
                    }
                query = query.filter(AiSolutionFeedback.target_key == target_key)
            else:
                query = query.filter(AiSolutionFeedback.ticket_id == ticket_id)
        elif normalized_surface == "recommendations_page" and recommendation_id:
            query = query.filter(AiSolutionFeedback.recommendation_id == recommendation_id)
        else:
            return {
                "current_feedback": None,
                "feedback_summary": _empty_feedback_summary(),
            }
        return _summarize_feedback_rows(query.all(), current_user_id=current_user_id)
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.warning("AI feedback bundle unavailable for %s: %s", normalized_surface or "unknown", exc)
        return {
            "current_feedback": None,
            "feedback_summary": _empty_feedback_summary(),
        }


def get_feedback_bundles_for_recommendations(
    db: Session,
    *,
    current_user_id,
    recommendation_ids: list[str],
) -> dict[str, dict[str, Any]]:
    normalized_ids = [item.strip() for item in recommendation_ids if item and item.strip()]
    if not normalized_ids:
        return {}
    try:
        rows = (
            db.query(AiSolutionFeedback)
            .filter(
                AiSolutionFeedback.source_surface == "recommendations_page",
                AiSolutionFeedback.recommendation_id.in_(normalized_ids),
            )
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.warning("Recommendation feedback bundles unavailable: %s", exc)
        return {}
    grouped: dict[str, list[AiSolutionFeedback]] = defaultdict(list)
    for row in rows:
        if row.recommendation_id:
            grouped[str(row.recommendation_id)].append(row)
    return {
        recommendation_id: _summarize_feedback_rows(grouped.get(recommendation_id, []), current_user_id=current_user_id)
        for recommendation_id in normalized_ids
    }


def aggregate_agent_feedback_analytics(
    db: Session,
    *,
    source_surface: str | None = None,
) -> dict[str, Any]:
    try:
        query = db.query(AiSolutionFeedback).filter(AiSolutionFeedback.feedback_type.in_(sorted(AGENT_FEEDBACK_TYPES)))
        normalized_surface = _normalize_feedback_type(source_surface)
        if normalized_surface in AGENT_FEEDBACK_SURFACES:
            query = query.filter(AiSolutionFeedback.source_surface == normalized_surface)
        rows = query.all()
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        logger.warning("Agent feedback analytics unavailable: %s", exc)
        summary = _empty_feedback_summary()
        summary["by_surface"] = {}
        summary["by_display_mode"] = {}
        summary["by_confidence_band"] = {}
        summary["by_recommendation_mode"] = {}
        summary["by_source_label"] = {}
        return summary
    summary = _summarize_feedback_rows(rows)["feedback_summary"]

    by_surface = _breakdown_summary(rows, labeler=lambda row: row.source_surface)
    by_display_mode = _breakdown_summary(rows, labeler=lambda row: row.display_mode_snapshot)
    by_confidence_band = _breakdown_summary(rows, labeler=_confidence_band_from_row)
    by_recommendation_mode = _breakdown_summary(
        rows,
        labeler=lambda row: (row.context_json or {}).get("recommendation_mode") if isinstance(row.context_json, dict) else None,
    )
    by_source_label = _breakdown_summary(
        rows,
        labeler=lambda row: (row.context_json or {}).get("source_label") if isinstance(row.context_json, dict) else row.source,
    )
    summary["by_surface"] = by_surface
    summary["by_display_mode"] = by_display_mode
    summary["by_confidence_band"] = by_confidence_band
    summary["by_recommendation_mode"] = by_recommendation_mode
    summary["by_source_label"] = by_source_label
    return summary
