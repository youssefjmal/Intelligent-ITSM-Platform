"""AI-based SLA risk scoring helper (shadow/assist advisory)."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from app.core.config import settings
from app.models.ticket import Ticket
from app.services.ai.llm import extract_json, ollama_generate

logger = logging.getLogger(__name__)

_ALLOWED_PRIORITIES = {"low", "medium", "high", "critical", "none"}


def _normalize_priority(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in _ALLOWED_PRIORITIES:
        return "None" if text == "none" else text.capitalize()
    return None


def _coerce_risk_score(value: Any) -> int | None:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _coerce_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, confidence))


def _safe_json_loads(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return extract_json(text)


def _status_age_minutes(ticket: Ticket, now: dt.datetime) -> int | None:
    updated_at = ticket.updated_at
    if updated_at is None:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=dt.timezone.utc)
    return max(int((now - updated_at).total_seconds() // 60), 0)


def _ticket_age_minutes(ticket: Ticket, now: dt.datetime) -> int | None:
    created_at = ticket.created_at
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.timezone.utc)
    return max(int((now - created_at).total_seconds() // 60), 0)


def _build_prompt(features: dict[str, Any]) -> str:
    feature_lines = "\n".join(
        [
            f"- sla_remaining_minutes: {features.get('sla_remaining_minutes')}",
            f"- breached: {features.get('breached')}",
            f"- status_age_minutes: {features.get('status_age_minutes')}",
            f"- priority: {features.get('priority')}",
            f"- category: {features.get('category')}",
            f"- assignee_role: {features.get('assignee_role')}",
            f"- similar_incidents: {features.get('similar_incidents')}",
            f"- ticket_age_minutes: {features.get('ticket_age_minutes')}",
        ]
    )
    return (
        "You are an IT Service Management risk assessor.\n\n"
        "Based only on the data below, estimate the probability\n"
        "that this ticket will breach its SLA or require escalation.\n\n"
        "Return JSON only:\n\n"
        "{\n"
        '  "risk_score": 0-100,\n'
        '  "confidence": 0-1,\n'
        '  "suggested_priority": "Low|Medium|High|Critical|None",\n'
        '  "reasoning_summary": "short explanation"\n'
        "}\n\n"
        "Be conservative.\n"
        "Do not hallucinate infrastructure details.\n"
        "Base reasoning strictly on provided features.\n\n"
        f"Ticket features:\n{feature_lines}\n"
    )


def evaluate_sla_risk(
    ticket: Ticket,
    *,
    assignee_role: str | None = None,
    similar_incidents: int | None = None,
) -> dict[str, Any]:
    """Return advisory AI SLA risk for a ticket; never raises."""
    now = dt.datetime.now(dt.timezone.utc)
    features = {
        "sla_remaining_minutes": ticket.sla_remaining_minutes,
        "breached": bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached),
        "status_age_minutes": _status_age_minutes(ticket, now),
        "priority": getattr(ticket.priority, "value", ticket.priority),
        "category": getattr(ticket.category, "value", ticket.category),
        "assignee_role": assignee_role or "unknown",
        "similar_incidents": similar_incidents,
        "ticket_age_minutes": _ticket_age_minutes(ticket, now),
    }
    model_version = settings.OLLAMA_MODEL

    fallback = {
        "risk_score": None,
        "confidence": None,
        "suggested_priority": None,
        "reasoning_summary": "AI SLA risk evaluation unavailable.",
        "model_version": model_version,
    }

    try:
        prompt = _build_prompt(features)
        raw = ollama_generate(prompt, json_mode=True)
        parsed = _safe_json_loads(raw)
        if not parsed:
            return fallback
        risk_score = _coerce_risk_score(parsed.get("risk_score"))
        confidence = _coerce_confidence(parsed.get("confidence"))
        suggested_priority = _normalize_priority(parsed.get("suggested_priority"))
        reasoning_summary = str(parsed.get("reasoning_summary") or "").strip()
        if not reasoning_summary:
            reasoning_summary = "AI model returned no reasoning summary."
        return {
            "risk_score": risk_score,
            "confidence": confidence,
            "suggested_priority": suggested_priority,
            "reasoning_summary": reasoning_summary,
            "model_version": model_version,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI SLA risk evaluation failed for ticket %s: %s", getattr(ticket, "id", "?"), exc)
        return fallback
