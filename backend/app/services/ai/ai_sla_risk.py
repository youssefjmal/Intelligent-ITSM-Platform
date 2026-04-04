"""AI-based SLA risk scoring helper (shadow/assist advisory)."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from app.core.config import settings
from app.models.ticket import Ticket
from app.services.ai.calibration import (
    AI_SLA_BACKLOG_WEIGHTS,
    AI_SLA_BAND_THRESHOLDS as _BAND_THRESHOLDS,
    AI_SLA_BLEND_WEIGHTS,
    AI_SLA_CONFIDENCE,
    AI_SLA_PRIORITY_FACTORS as _PRIORITY_FACTORS,
)
from app.services.ai.llm import extract_json, ollama_generate

logger = logging.getLogger(__name__)

_ALLOWED_PRIORITIES = {"low", "medium", "high", "critical", "none"}
_ACTIVE_STATUSES = {"open", "in_progress", "pending", "waiting_for_customer", "waiting_for_support_vendor"}

# Language-aware strings for SLA risk reasoning and actions.
# Add new languages by adding a key to these dicts.
# Default falls back to "fr" if language is not found.
_SLA_REASON_BREACHED = {
    "fr": "Le d\u00e9lai SLA est d\u00e9j\u00e0 d\u00e9pass\u00e9 pour ce ticket.",
    "en": "SLA deadline is already breached for this ticket.",
}
_SLA_REASON_CONSUMED = {
    "fr": "Le ticket a consomm\u00e9 {pct}% de la fen\u00eatre SLA.",
    "en": "Ticket has consumed {pct}% of the SLA window.",
}
_SLA_REASON_INACTIVITY_LONG = {
    "fr": "Aucune activit\u00e9 enregistr\u00e9e depuis {dur}.",
    "en": "No activity recorded in the last {dur}.",
}
_SLA_REASON_INACTIVITY_SHORT = {
    "fr": "Derni\u00e8re activit\u00e9 sur le ticket il y a {dur}.",
    "en": "Last ticket activity was {dur} ago.",
}
_SLA_REASON_ASSIGNEE_LOAD = {
    "fr": "L'assignataire actuel g\u00e8re d\u00e9j\u00e0 {n} autres tickets actifs.",
    "en": "Current assignee already owns {n} other active tickets.",
}
_SLA_REASON_QUEUE_PRESSURE = {
    "fr": "Il y a {n} tickets actifs dans la m\u00eame cat\u00e9gorie, indiquant une pression sur la file.",
    "en": "There are {n} active tickets in the same category, indicating queue pressure.",
}
_SLA_REASON_REMAINING = {
    "fr": "Il ne reste que {dur} avant l'objectif SLA.",
    "en": "Only {dur} remain before the SLA target.",
}
_SLA_REASON_PRIORITY = {
    "fr": "La priorit\u00e9 du ticket est {priority}, ce qui r\u00e9duit la fen\u00eatre de r\u00e9ponse s\u00fbr.",
    "en": "Ticket priority is {priority}, which narrows the safe response window.",
}
_SLA_REASON_OK = {
    "fr": "Le ticket est dans les limites SLA et dispose de suffisamment de temps restant.",
    "en": "Ticket is within SLA and has enough remaining time for the current workflow.",
}
_SLA_ACTIONS = {
    "low": {
        "fr": [
            "Aucune action imm\u00e9diate requise pour l'instant.",
            "Maintenez le ticket en mouvement et rev\u00e9rifiez avant que la fen\u00eatre SLA ne se resserre.",
        ],
        "en": [
            "No immediate action required yet.",
            "Keep the ticket moving and review it again before the SLA window tightens.",
        ],
    },
    "medium": {
        "fr": [
            "V\u00e9rifiez l'avancement du ticket avec l'assignataire.",
            "Assurez-vous que l'assignataire a confirm\u00e9 la prochaine \u00e9tape op\u00e9rationnelle.",
        ],
        "en": [
            "Check ticket progress with the assignee.",
            "Ensure the assignee has acknowledged the next operational step.",
        ],
    },
    "high": {
        "fr": [
            "Relancez l'assignataire maintenant.",
            "R\u00e9assignez le ticket s'il reste inactif apr\u00e8s la relance.",
            "Escaladez si le ticket n'est toujours pas r\u00e9solu dans {window} minutes.",
        ],
        "en": [
            "Follow up with the assignee now.",
            "Reassign the ticket if it remains inactive after the follow-up.",
            "Escalate if the ticket is still unresolved in {window} minutes.",
        ],
    },
    "critical_breach": {
        "fr": "Notifiez le chef d'\u00e9quipe que le ticket est d\u00e9j\u00e0 hors SLA.",
        "en": "Notify the team lead that the ticket is already outside SLA.",
    },
    "critical_imminent": {
        "fr": "Notifiez le chef d'\u00e9quipe que le breach SLA est imminent.",
        "en": "Notify the team lead that the SLA breach is imminent.",
    },
    "critical_base": {
        "fr": [
            "Escaladez imm\u00e9diatement le ticket au chef d'\u00e9quipe.",
            "R\u00e9assignez ou mobilisez une \u00e9quipe maintenant si le propri\u00e9taire actuel est inactif.",
        ],
        "en": [
            "Escalate the ticket to the team lead immediately.",
            "Reassign or swarm the ticket now if the current owner is inactive.",
        ],
    },
}


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


def _coerce_unit_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score <= 1.0:
        return max(0.0, min(score, 1.0))
    return max(0.0, min(score / 100.0, 1.0))


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


def _status_value(ticket: Ticket) -> str:
    value = getattr(getattr(ticket, "status", None), "value", getattr(ticket, "status", None))
    return str(value or "").strip().lower()


def _priority_value(ticket: Ticket) -> str:
    value = getattr(getattr(ticket, "priority", None), "value", getattr(ticket, "priority", None))
    return str(value or "").strip().lower()


def _safe_minutes(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def _band_from_score(score: float) -> str:
    for threshold, label in _BAND_THRESHOLDS:
        if score >= threshold:
            return label
    return "low"


def _format_minutes(value: int | None) -> str:
    if value is None:
        return "unknown time"
    if value < 60:
        return f"{value} minute{'s' if value != 1 else ''}"
    hours, minutes = divmod(value, 60)
    if minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours}h {minutes}m"


def _sla_elapsed_ratio(ticket: Ticket, now: dt.datetime) -> float:
    if bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached):
        return 1.0

    elapsed_minutes = _safe_minutes(getattr(ticket, "sla_elapsed_minutes", None))
    remaining_minutes = _safe_minutes(getattr(ticket, "sla_remaining_minutes", None))
    if elapsed_minutes is not None:
        total = elapsed_minutes + max(remaining_minutes or 0, 0)
        if total > 0:
            return _clamp_unit(elapsed_minutes / total)

    ticket_age = _ticket_age_minutes(ticket, now)
    if ticket_age is not None and remaining_minutes is not None:
        total = ticket_age + max(remaining_minutes, 0)
        if total > 0:
            return _clamp_unit(ticket_age / total)

    return 0.0


def _inactivity_factor(ticket: Ticket, now: dt.datetime) -> tuple[float, int | None]:
    status_age = _status_age_minutes(ticket, now)
    status = _status_value(ticket)
    if status in {"resolved", "closed"}:
        return 0.0, status_age
    if status_age is None:
        return 0.0, None
    divisor = 180 if status in {"open", "in_progress"} else 240
    factor = _clamp_unit(status_age / divisor)
    if status in {"waiting_for_customer", "pending"}:
        factor *= 0.75
    return round(_clamp_unit(factor), 3), status_age


def _backlog_pressure(*, similar_incidents: int | None, assignee_load: int | None) -> float:
    similar_factor = _clamp_unit((similar_incidents or 0) / 6.0) if similar_incidents is not None else 0.0
    assignee_factor = _clamp_unit((assignee_load or 0) / 8.0) if assignee_load is not None else 0.0
    if similar_incidents is None and assignee_load is None:
        return 0.0
    if similar_incidents is None:
        return round(assignee_factor, 3)
    if assignee_load is None:
        return round(similar_factor, 3)
    return round(
        _clamp_unit(
            (similar_factor * AI_SLA_BACKLOG_WEIGHTS["similar_incidents"])
            + (assignee_factor * AI_SLA_BACKLOG_WEIGHTS["assignee_load"])
        ),
        3,
    )


def _deterministic_confidence(
    *,
    ratio_known: bool,
    inactivity_known: bool,
    backlog_known: bool,
    risk_score: float,
    ai_confidence: float | None,
) -> float:
    confidence = AI_SLA_CONFIDENCE["base"]
    confidence += AI_SLA_CONFIDENCE["ratio_known_bonus"] if ratio_known else 0.0
    confidence += AI_SLA_CONFIDENCE["inactivity_known_bonus"] if inactivity_known else 0.0
    confidence += AI_SLA_CONFIDENCE["backlog_known_bonus"] if backlog_known else 0.0
    confidence += (
        AI_SLA_CONFIDENCE["high_risk_bonus"]
        if risk_score >= 0.8
        else (AI_SLA_CONFIDENCE["medium_risk_bonus"] if risk_score >= 0.6 else 0.0)
    )
    if ai_confidence is not None:
        confidence = max(
            confidence,
            (ai_confidence * AI_SLA_CONFIDENCE["ai_weight"]) + AI_SLA_CONFIDENCE["ai_bias"],
        )
    return round(_clamp_unit(confidence), 3)


def _suggested_priority(ticket: Ticket, *, band: str, ai_suggested_priority: str | None) -> str | None:
    if ai_suggested_priority:
        return ai_suggested_priority
    current = _priority_value(ticket)
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    current_rank = rank.get(current, 2)
    if band == "critical" and current_rank < 4:
        return "Critical"
    if band == "high" and current_rank < 3:
        return "High"
    if band == "medium" and current_rank < 2:
        return "Medium"
    return None


def _build_reasoning(
    ticket: Ticket,
    *,
    ratio: float,
    inactivity_minutes: int | None,
    similar_incidents: int | None,
    assignee_load: int | None,
    lang: str = "fr",
) -> list[str]:
    _lang = lang if lang in ("fr", "en") else "fr"
    reasons: list[str] = []
    status = _status_value(ticket)
    remaining_minutes = _safe_minutes(getattr(ticket, "sla_remaining_minutes", None))

    if bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached):
        reasons.append(_SLA_REASON_BREACHED[_lang])
    elif ratio > 0:
        reasons.append(_SLA_REASON_CONSUMED[_lang].format(pct=round(ratio * 100)))

    if inactivity_minutes is not None:
        if inactivity_minutes >= 60:
            reasons.append(_SLA_REASON_INACTIVITY_LONG[_lang].format(dur=_format_minutes(inactivity_minutes)))
        else:
            reasons.append(_SLA_REASON_INACTIVITY_SHORT[_lang].format(dur=_format_minutes(inactivity_minutes)))

    if assignee_load is not None and assignee_load >= 4:
        reasons.append(_SLA_REASON_ASSIGNEE_LOAD[_lang].format(n=assignee_load))
    elif similar_incidents is not None and similar_incidents >= 4:
        reasons.append(_SLA_REASON_QUEUE_PRESSURE[_lang].format(n=similar_incidents))

    if remaining_minutes is not None and remaining_minutes <= 30 and status in _ACTIVE_STATUSES:
        reasons.append(_SLA_REASON_REMAINING[_lang].format(dur=_format_minutes(max(remaining_minutes, 0))))
    elif _priority_value(ticket) in {"high", "critical"} and status in _ACTIVE_STATUSES:
        reasons.append(_SLA_REASON_PRIORITY[_lang].format(priority=_priority_value(ticket)))

    if not reasons:
        reasons.append(_SLA_REASON_OK[_lang])

    return reasons[:4]


def _build_actions(*, band: str, remaining_minutes: int | None, lang: str = "fr") -> list[str]:
    _lang = lang if lang in ("fr", "en") else "fr"
    if band == "low":
        return list(_SLA_ACTIONS["low"][_lang])
    if band == "medium":
        return list(_SLA_ACTIONS["medium"][_lang])
    if band == "high":
        follow_up_window = max(15, min(60, remaining_minutes or 30))
        base = list(_SLA_ACTIONS["high"][_lang])
        return [base[0], base[1], base[2].format(window=follow_up_window)]
    breach_text = (
        _SLA_ACTIONS["critical_breach"][_lang]
        if remaining_minutes is not None and remaining_minutes <= 0
        else _SLA_ACTIONS["critical_imminent"][_lang]
    )
    return list(_SLA_ACTIONS["critical_base"][_lang]) + [breach_text]


def build_sla_advisory(
    ticket: Ticket,
    *,
    similar_incidents: int | None = None,
    assignee_load: int | None = None,
    ai_evaluation: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    lang: str = "fr",
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    ratio = _sla_elapsed_ratio(ticket, now)
    inactivity_factor, inactivity_minutes = _inactivity_factor(ticket, now)
    backlog = _backlog_pressure(similar_incidents=similar_incidents, assignee_load=assignee_load)
    priority_factor = _PRIORITY_FACTORS.get(_priority_value(ticket), 0.45)

    status = _status_value(ticket)
    if status in {"resolved", "closed"}:
        risk_score = 0.08
    else:
        risk_score = (0.5 * ratio) + (0.2 * inactivity_factor) + (0.2 * backlog) + (0.1 * priority_factor)
        if bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached):
            risk_score = max(risk_score, 0.95)
        risk_score = _clamp_unit(risk_score)

    ai_score = _coerce_unit_score(ai_evaluation.get("risk_score")) if isinstance(ai_evaluation, dict) else None
    ai_confidence = _coerce_confidence(ai_evaluation.get("confidence")) if isinstance(ai_evaluation, dict) else None
    advisory_mode = "deterministic"
    if ai_score is not None:
        risk_score = round(
            _clamp_unit(
                (risk_score * AI_SLA_BLEND_WEIGHTS["deterministic"])
                + (ai_score * AI_SLA_BLEND_WEIGHTS["ai"])
            ),
            3,
        )
        advisory_mode = "hybrid"

    band = _band_from_score(risk_score)
    remaining_minutes = _safe_minutes(getattr(ticket, "sla_remaining_minutes", None))
    confidence = _deterministic_confidence(
        ratio_known=ratio > 0 or _safe_minutes(getattr(ticket, "sla_elapsed_minutes", None)) is not None,
        inactivity_known=inactivity_minutes is not None,
        backlog_known=similar_incidents is not None or assignee_load is not None,
        risk_score=risk_score,
        ai_confidence=ai_confidence if advisory_mode == "hybrid" else None,
    )
    reasoning = _build_reasoning(
        ticket,
        ratio=risk_score if band == "critical" and ratio == 0 and bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached) else ratio,
        inactivity_minutes=inactivity_minutes,
        similar_incidents=similar_incidents,
        assignee_load=assignee_load,
        lang=lang,
    )
    recommended_actions = _build_actions(band=band, remaining_minutes=remaining_minutes, lang=lang)
    suggested_priority = _suggested_priority(
        ticket,
        band=band,
        ai_suggested_priority=_normalize_priority(ai_evaluation.get("suggested_priority")) if isinstance(ai_evaluation, dict) else None,
    )

    evaluated_at = now.isoformat()
    return {
        "risk_score": round(risk_score, 3),
        "band": band,
        "confidence": confidence,
        "reasoning": reasoning,
        "recommended_actions": recommended_actions,
        "advisory_mode": advisory_mode,
        "evaluated_at": evaluated_at,
        "suggested_priority": suggested_priority,
        "sla_elapsed_ratio": round(ratio, 3),
        "time_consumed_percent": max(0, min(100, int(round(ratio * 100)))),
    }


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
