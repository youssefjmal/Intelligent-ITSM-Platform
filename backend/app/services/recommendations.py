"""Service helpers for evidence-backed recommendation queries."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import (
    ProblemStatus,
    RecommendationImpact,
    RecommendationType,
    TicketPriority,
    TicketStatus,
)
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ai import RetrievalResult
from app.services.ai.classifier import classify_ticket_detailed, score_recommendations
from app.services.ai.feedback import get_feedback_bundles_for_recommendations
from app.services.ai.resolver import (
    build_manual_triage_advice_payload,
    build_ticket_retrieval_query as _shared_ticket_retrieval_query,
    candidate_tickets_for_ticket as _shared_candidate_tickets_for_ticket,
    resolve_ticket_advice,
    resolution_advice_to_payload,
)
from app.services.ai.orchestrator import get_sla_strategies_advice
from app.services.ai.routing_validation import validate_ticket_routing, validate_ticket_routing_for_ticket
from app.services.ai.resolution_advisor import build_resolution_advice
from app.services.ai.retrieval import unified_retrieve
from app.services.ai.service_requests import (
    build_service_request_profile,
    build_service_request_guidance,
)
from app.services.tickets import list_tickets_for_user

logger = logging.getLogger(__name__)

_ACTIVE_TICKET_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}
_ACTIVE_PROBLEM_STATUSES = {
    ProblemStatus.open,
    ProblemStatus.investigating,
    ProblemStatus.known_error,
}
_MAX_CRITICAL_TICKETS = 3
_MAX_ACTIVE_PROBLEMS = 2
_MAX_RECOMMENDATIONS = 18


@dataclass(slots=True)
class RecommendationView:
    id: str
    type: RecommendationType
    entity_type: str
    title: str
    description: str
    recommended_action: str | None
    reasoning: str | None
    related_tickets: list[str]
    confidence: float
    confidence_band: str
    confidence_label: str
    impact: RecommendationImpact
    tentative: bool
    probable_root_cause: str | None
    root_cause: str | None
    supporting_context: str | None
    source_label: str
    recommendation_mode: str
    action_relevance_score: float
    filtered_weak_match: bool
    mode: str
    display_mode: str
    match_summary: str | None
    why_this_matches: list[str]
    next_best_actions: list[str]
    validation_steps: list[str]
    base_recommended_action: str | None
    base_next_best_actions: list[str]
    base_validation_steps: list[str]
    action_refinement_source: str | None
    evidence_sources: list[dict[str, Any]]
    created_at: dt.datetime
    llm_general_advisory: dict[str, Any] | None = None
    current_feedback: dict[str, Any] | None = None
    feedback_summary: dict[str, Any] | None = None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _lang(locale: str | None = None) -> str:
    value = str(locale or "").strip().lower()
    return "fr" if value.startswith("fr") else "en"


def _clamp_unit_confidence(value: float, *, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return round(max(floor, min(ceiling, float(value))), 4)


def _confidence_band(value: float) -> str:
    if value >= 0.78:
        return "high"
    if value >= 0.52:
        return "medium"
    return "low"


def _ai_rec_id(*parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()
    return f"AI-{digest}"


def _impact_for_ticket(priority: TicketPriority) -> RecommendationImpact:
    if priority in {TicketPriority.critical, TicketPriority.high}:
        return RecommendationImpact.high
    if priority == TicketPriority.medium:
        return RecommendationImpact.medium
    return RecommendationImpact.low


def _is_active_ticket(ticket: Ticket) -> bool:
    return ticket.status in _ACTIVE_TICKET_STATUSES


def _normalize_line(value: Any) -> str:
    raw = getattr(value, "value", value)
    return " ".join(str(raw or "").strip().split())


def _ticket_retrieval_query(ticket: Ticket) -> str:
    return _shared_ticket_retrieval_query(ticket, include_priority=True)


def _problem_retrieval_query(problem: Problem, linked_tickets: list[Ticket]) -> str:
    ticket_titles = "; ".join(str(ticket.title or "").strip() for ticket in linked_tickets[:3] if str(ticket.title or "").strip())
    return "\n".join(
        [
            str(problem.title or "").strip(),
            str(getattr(problem, "description", "") or "").strip(),
            str(problem.root_cause or "").strip(),
            ticket_titles,
        ]
    ).strip()


def _candidate_tickets_for_recommendation(ticket: Ticket, visible_tickets: list[Ticket]) -> list[Ticket]:
    return list(_shared_candidate_tickets_for_ticket(ticket, visible_tickets))


def _normalized_evidence_sources(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in list(value or []):
        reference = _normalize_line(raw.get("reference"))
        if not reference:
            continue
        rows.append(
            {
                "evidence_type": _normalize_line(raw.get("evidence_type")),
                "reference": reference,
                "excerpt": _normalize_line(raw.get("excerpt")) or None,
                "source_id": _normalize_line(raw.get("source_id")) or None,
                "title": _normalize_line(raw.get("title")) or None,
                "relevance": _clamp_unit_confidence(float(raw.get("relevance") or 0.0)),
                "why_relevant": _normalize_line(raw.get("why_relevant")) or None,
            }
        )
    return rows[:3]


def _normalize_resolution_payload(
    advice_payload: dict[str, Any] | None,
    *,
    default_source_label: str,
) -> dict[str, Any] | None:
    if not isinstance(advice_payload, dict):
        return None
    recommended_action = _normalize_line(advice_payload.get("recommended_action")) or None
    display_mode = _normalize_line(advice_payload.get("display_mode")) or "evidence_action"
    reasoning = _normalize_line(advice_payload.get("reasoning")) or None
    if not recommended_action and display_mode != "no_strong_match" and not reasoning:
        return None
    return {
        "recommended_action": recommended_action,
        "reasoning": reasoning,
        "probable_root_cause": _normalize_line(advice_payload.get("probable_root_cause")) or None,
        "root_cause": _normalize_line(advice_payload.get("root_cause")) or _normalize_line(advice_payload.get("probable_root_cause")) or None,
        "supporting_context": _normalize_line(advice_payload.get("supporting_context")) or None,
        "evidence_sources": _normalized_evidence_sources(advice_payload.get("evidence_sources")),
        "tentative": bool(advice_payload.get("tentative", False)),
        "confidence": _clamp_unit_confidence(float(advice_payload.get("confidence") or 0.0)),
        "confidence_band": _normalize_line(advice_payload.get("confidence_band")) or _confidence_band(float(advice_payload.get("confidence") or 0.0)),
        "confidence_label": _normalize_line(advice_payload.get("confidence_label")) or _normalize_line(advice_payload.get("confidence_band")) or _confidence_band(float(advice_payload.get("confidence") or 0.0)),
        "source_label": _normalize_line(advice_payload.get("source_label")) or default_source_label,
        "recommendation_mode": _normalize_line(advice_payload.get("recommendation_mode")) or "fallback_rules",
        "action_relevance_score": _clamp_unit_confidence(float(advice_payload.get("action_relevance_score") or 0.0)),
        "filtered_weak_match": bool(advice_payload.get("filtered_weak_match", False)),
        "mode": _normalize_line(advice_payload.get("mode")) or display_mode,
        "display_mode": display_mode,
        "match_summary": _normalize_line(advice_payload.get("match_summary")) or None,
        "why_this_matches": [
            _normalize_line(item)
            for item in list(advice_payload.get("why_this_matches") or [])
            if _normalize_line(item)
        ][:4],
        "next_best_actions": [
            _normalize_line(item)
            for item in list(advice_payload.get("next_best_actions") or [])
            if _normalize_line(item)
        ][:4],
        "validation_steps": [
            _normalize_line(item)
            for item in list(advice_payload.get("validation_steps") or [])
            if _normalize_line(item)
        ][:3],
        "base_recommended_action": _normalize_line(advice_payload.get("base_recommended_action")) or None,
        "base_next_best_actions": [
            _normalize_line(item)
            for item in list(advice_payload.get("base_next_best_actions") or [])
            if _normalize_line(item)
        ][:4],
        "base_validation_steps": [
            _normalize_line(item)
            for item in list(advice_payload.get("base_validation_steps") or [])
            if _normalize_line(item)
        ][:3],
        "action_refinement_source": _normalize_line(advice_payload.get("action_refinement_source")) or None,
        "llm_general_advisory": advice_payload.get("llm_general_advisory")
        if isinstance(advice_payload.get("llm_general_advisory"), dict)
        else None,
    }


def _fallback_resolution_from_classifier(
    *,
    details: dict[str, Any],
    retrieval: dict[str, Any],
    lang: str,
) -> dict[str, Any] | None:
    actions = [
        _normalize_line(item)
        for item in [
            *(details.get("recommendations") or []),
            *(details.get("recommendations_embedding") or []),
            *(details.get("recommendations_llm") or []),
        ]
        if _normalize_line(item)
    ]
    deduped = list(dict.fromkeys(actions))
    if not deduped:
        return None
    _cls_conf: int | None = details.get("classification_confidence")
    scored = score_recommendations(deduped, start_confidence=76, rank_decay=8, floor=54, ceiling=82, classification_confidence=_cls_conf)
    if not scored:
        return None
    first = scored[0]
    action = _normalize_line(first.get("text"))
    if not action:
        return None
    confidence = _clamp_unit_confidence((int(first.get("confidence") or 60) / 100.0) - 0.1, floor=0.42, ceiling=0.72)
    reasoning = (
        "Aucune resolution explicite n'a ete retrouvee; cette action provient du repli deterministe base sur les signaux du ticket."
        if lang == "fr"
        else "No explicit historical fix was retrieved; this action comes from the deterministic fallback based on the ticket signals."
    )
    probable_root_cause = None
    for row in list(retrieval.get("related_problems") or []):
        root_cause = _normalize_line(row.get("root_cause"))
        if root_cause:
            probable_root_cause = root_cause
            break
    return {
        "recommended_action": action,
        "reasoning": reasoning,
        "probable_root_cause": probable_root_cause,
        "evidence_sources": [],
        "tentative": True,
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "source_label": _normalize_line(retrieval.get("source")) or "fallback_rules",
        "recommendation_mode": "fallback_diagnostic",
        "action_relevance_score": confidence,
        "filtered_weak_match": False,
        "display_mode": "tentative_diagnostic",
        "match_summary": None,
        "next_best_actions": [
            (
                "Validez l'action sur un ticket affecte avant generalisation."
                if lang == "fr"
                else "Validate the action on one affected ticket before wider rollout."
            ),
            (
                "Documentez la resolution retenue avant cloture."
                if lang == "fr"
                else "Document the chosen resolution before closure."
            ),
        ],
    }


def _legacy_recommendations(
    db: Session,
    *,
    visible_ticket_ids: set[str],
    lang: str,
) -> list[RecommendationView]:
    if not hasattr(db, "query"):
        return []
    rows = db.query(Recommendation).order_by(Recommendation.created_at.desc()).all()
    filtered = [
        row
        for row in rows
        if not row.related_tickets
        or any(ticket_id in visible_ticket_ids for ticket_id in row.related_tickets)
    ]
    reasoning = (
        "Recommendation historique conservee depuis le flux legacy."
        if lang == "fr"
        else "Historical recommendation carried over from the legacy feed."
    )
    return [
        RecommendationView(
            id=row.id,
            type=row.type,
            entity_type="legacy",
            title=row.title,
            description=row.description,
            recommended_action=_normalize_line(row.description) or row.title,
            reasoning=reasoning,
            related_tickets=list(row.related_tickets or []),
            confidence=_clamp_unit_confidence(float(row.confidence or 0) / 100.0),
            confidence_band=_confidence_band(float(row.confidence or 0) / 100.0),
            confidence_label=_confidence_band(float(row.confidence or 0) / 100.0),
            impact=row.impact,
            tentative=False,
            probable_root_cause=None,
            root_cause=None,
            supporting_context=None,
            source_label="legacy_store",
            recommendation_mode="fallback_rules",
            action_relevance_score=_clamp_unit_confidence(float(row.confidence or 0) / 100.0),
            filtered_weak_match=False,
            mode="evidence_action",
            display_mode="evidence_action",
            match_summary=None,
            why_this_matches=[],
            next_best_actions=[],
            evidence_sources=[],
            created_at=row.created_at or _utcnow(),
            current_feedback=None,
            feedback_summary=None,
        )
        for row in filtered
    ]


def _workflow_description(entity_id: str, action: str, *, lang: str) -> str:
    if lang == "fr":
        return (
            f"Appliquez d'abord l'action recommande pour {entity_id}, puis validez le resultat sur les tickets affectes "
            "et documentez la resolution avant cloture."
        )
    return (
        f"Apply the recommended action for {entity_id}, validate the outcome on affected tickets, "
        "and document the resolution before closure."
    )


def _priority_rank(priority: TicketPriority) -> int:
    order = {
        TicketPriority.low: 0,
        TicketPriority.medium: 1,
        TicketPriority.high: 2,
        TicketPriority.critical: 3,
    }
    return order.get(priority, 0)


def _first_evidence_reference(
    advice: dict[str, Any],
    *,
    preferred_types: set[str] | None = None,
) -> str | None:
    for row in list(advice.get("evidence_sources") or []):
        evidence_type = _normalize_line(row.get("evidence_type")).casefold()
        if preferred_types and evidence_type not in preferred_types:
            continue
        reference = _normalize_line(row.get("reference"))
        if reference:
            return reference
    return None


def _pattern_recommended_action(entity_id: str, advice: dict[str, Any], *, lang: str) -> str:
    reference = _first_evidence_reference(
        advice,
        preferred_types={"resolved ticket", "similar ticket"},
    ) or _first_evidence_reference(advice)
    if lang == "fr":
        if reference:
            return (
                f"Validez que {entity_id} correspond au pattern observe dans {reference} "
                "avant de reutiliser le chemin de resolution confirme."
            )
        return f"Validez que {entity_id} correspond au pattern incident observe avant de reutiliser la resolution confirmee."
    if reference:
        return (
            f"Confirm that {entity_id} matches the incident pattern seen in {reference} "
            "before reusing the validated fix path."
        )
    return f"Confirm that {entity_id} matches the observed incident pattern before reusing the validated fix path."


def _pattern_next_best_actions(entity_id: str, advice: dict[str, Any], *, lang: str) -> list[str]:
    reference = _first_evidence_reference(
        advice,
        preferred_types={"resolved ticket", "similar ticket"},
    ) or _first_evidence_reference(advice)
    if lang == "fr":
        steps = [
            f"Comparez les symptomes de {entity_id} avec les incidents similaires recuperes.",
            "Confirmez que le perimetre, l'impact et la cause probable sont alignes.",
            "Reutilisez uniquement la resolution validee si le pattern reste coherent.",
        ]
        if reference:
            steps[0] = f"Comparez les symptomes de {entity_id} avec {reference} et les incidents similaires recuperes."
        return steps
    steps = [
        f"Compare the symptoms for {entity_id} against the retrieved similar incidents.",
        "Confirm that scope, impact, and probable cause are aligned.",
        "Reuse the validated fix only if the pattern remains consistent.",
    ]
    if reference:
        steps[0] = f"Compare the symptoms for {entity_id} against {reference} and the retrieved similar incidents."
    return steps


def _priority_recommended_action(
    entity_id: str,
    *,
    current_priority: TicketPriority,
    suggested_priority: TicketPriority,
    lang: str,
) -> str:
    increase = _priority_rank(suggested_priority) > _priority_rank(current_priority)
    if lang == "fr":
        if increase:
            return (
                f"Augmentez la priorite de {entity_id} de {current_priority.value} vers {suggested_priority.value} "
                "et alignez le triage avec le risque observe."
            )
        return (
            f"Reevaluez la priorite de {entity_id} de {current_priority.value} vers {suggested_priority.value} "
            "apres confirmation de l'impact et de l'urgence."
        )
    if increase:
        return (
            f"Raise the priority for {entity_id} from {current_priority.value} to {suggested_priority.value} "
            "and align triage with the observed risk."
        )
    return (
        f"Reassess the priority for {entity_id} from {current_priority.value} to {suggested_priority.value} "
        "after confirming impact and urgency."
    )


def _priority_next_best_actions(
    entity_id: str,
    *,
    current_priority: TicketPriority,
    suggested_priority: TicketPriority,
    lang: str,
) -> list[str]:
    if lang == "fr":
        return [
            f"Mettez a jour la priorite de {entity_id} vers {suggested_priority.value}.",
            "Confirmez l'assignation et le delai de prise en charge attendus.",
            "Ajustez les escalades SLA si le niveau de risque change.",
        ]
    return [
        f"Update the priority for {entity_id} to {suggested_priority.value}.",
        "Confirm ownership and the expected response target.",
        "Adjust SLA escalation handling if the risk level changes.",
    ]


def _workflow_recommended_action(entity_id: str, action: str, *, lang: str) -> str:
    if lang == "fr":
        return (
            f"Executez l'action validee pour {entity_id}, puis verifiez le resultat sur les tickets affectes "
            "avant de cloturer."
        )
    return (
        f"Execute the validated action for {entity_id}, then verify the outcome across affected tickets "
        "before closing."
    )


def _workflow_next_best_actions(entity_id: str, action: str, *, lang: str) -> list[str]:
    normalized_action = _normalize_line(action)
    if lang == "fr":
        steps = [
            normalized_action or f"Appliquez l'action validee pour {entity_id}.",
            "Validez le resultat sur les tickets lies et les utilisateurs affectes.",
            "Documentez la preuve de resolution avant cloture.",
        ]
        return [step for step in steps if step]
    steps = [
        normalized_action or f"Apply the validated action for {entity_id}.",
        "Validate the outcome on linked tickets and affected users.",
        "Document the resolution evidence before closure.",
    ]
    return [step for step in steps if step]


def _problem_pattern_recommended_action(problem: Problem, *, lang: str) -> str:
    if lang == "fr":
        return (
            f"Confirmez que les tickets lies a {problem.id} suivent le meme pattern recurrent "
            "avant de reutiliser la resolution problematique."
        )
    return (
        f"Confirm that the tickets linked to {problem.id} follow the same recurring pattern "
        "before reusing the problem-level resolution."
    )


def _problem_pattern_next_best_actions(problem: Problem, *, lang: str) -> list[str]:
    if lang == "fr":
        return [
            f"Comparez les symptomes des tickets lies a {problem.id}.",
            "Validez que la cause probable reste identique sur les incidents actifs.",
            "Reutilisez la resolution problematique uniquement si le pattern est confirme.",
        ]
    return [
        f"Compare the symptoms across tickets linked to {problem.id}.",
        "Validate that the probable cause is still the same across active incidents.",
        "Reuse the problem resolution only if the pattern is confirmed.",
    ]


def _problem_workflow_recommended_action(problem: Problem, *, lang: str) -> str:
    if lang == "fr":
        return (
            f"Appliquez la resolution retenue pour {problem.id}, verifiez le resultat sur les incidents lies "
            "et documentez la validation finale."
        )
    return (
        f"Apply the selected resolution for {problem.id}, verify the outcome across linked incidents, "
        "and document the final validation."
    )


def _problem_workflow_next_best_actions(problem: Problem, action: str, *, lang: str) -> list[str]:
    normalized_action = _normalize_line(action)
    if lang == "fr":
        return [
            normalized_action or f"Appliquez la resolution retenue pour {problem.id}.",
            "Validez le resultat sur les incidents lies encore actifs.",
            "Documentez la preuve de correction problematique avant cloture.",
        ]
    return [
        normalized_action or f"Apply the selected resolution for {problem.id}.",
        "Validate the outcome on still-active linked incidents.",
        "Document the problem-resolution evidence before closure.",
    ]


def _problem_priority_recommended_action(problem: Problem, *, lang: str) -> str:
    if lang == "fr":
        return (
            f"Traitez {problem.id} comme prioritaire tant que des incidents critiques lies restent actifs."
        )
    return (
        f"Treat {problem.id} as a priority while critical linked incidents remain active."
    )


def _problem_priority_next_best_actions(problem: Problem, *, lang: str) -> list[str]:
    if lang == "fr":
        return [
            f"Priorisez {problem.id} dans la file de traitement.",
            "Coordonnez les incidents critiques lies pendant l'execution de la correction.",
            "Confirmez la reduction du risque avant de baisser la priorite.",
        ]
    return [
        f"Prioritize {problem.id} in the active work queue.",
        "Coordinate the linked critical incidents while executing the fix.",
        "Confirm the risk has reduced before lowering priority.",
    ]


def _advice_with_overrides(
    advice: dict[str, Any],
    *,
    recommended_action: str | None = None,
    reasoning: str | None = None,
    next_best_actions: list[str] | None = None,
) -> dict[str, Any]:
    payload = dict(advice)
    if recommended_action is not None:
        payload["recommended_action"] = _normalize_line(recommended_action) or None
    if reasoning is not None:
        payload["reasoning"] = _normalize_line(reasoning) or None
    if next_best_actions is not None:
        payload["next_best_actions"] = [
            _normalize_line(item)
            for item in next_best_actions
            if _normalize_line(item)
        ][:4]
    return payload


def _build_view(
    *,
    entity_prefix: str,
    entity_id: str,
    entity_type: str,
    recommendation_type: RecommendationType,
    title: str,
    description: str,
    related_tickets: list[str],
    impact: RecommendationImpact,
    created_at: dt.datetime,
    advice: dict[str, Any],
    confidence_offset: float = 0.0,
) -> RecommendationView:
    raw_mode = advice.get("mode") or advice.get("display_mode") or "evidence_action"
    raw_display_mode = advice.get("display_mode") or "evidence_action"
    normalized_confidence = _clamp_unit_confidence(float(advice.get("confidence") or 0.0) + confidence_offset)
    return RecommendationView(
        id=_ai_rec_id(entity_prefix, entity_id, recommendation_type.value),
        type=recommendation_type,
        entity_type=entity_type,
        title=title,
        description=description,
        recommended_action=str(advice.get("recommended_action") or "").strip() or None,
        reasoning=str(advice.get("reasoning") or "").strip() or None,
        related_tickets=related_tickets,
        confidence=normalized_confidence,
        confidence_band=_confidence_band(normalized_confidence),
        confidence_label=str(advice.get("confidence_label") or _confidence_band(normalized_confidence)),
        impact=impact,
        tentative=bool(advice.get("tentative", False)),
        probable_root_cause=str(advice.get("probable_root_cause") or "").strip() or None,
        root_cause=str(advice.get("root_cause") or advice.get("probable_root_cause") or "").strip() or None,
        supporting_context=str(advice.get("supporting_context") or "").strip() or None,
        source_label=str(advice.get("source_label") or "fallback_rules"),
        recommendation_mode=str(advice.get("recommendation_mode") or "fallback_rules"),
        action_relevance_score=_clamp_unit_confidence(float(advice.get("action_relevance_score") or 0.0)),
        filtered_weak_match=bool(advice.get("filtered_weak_match", False)),
        mode=str(getattr(raw_mode, "value", raw_mode) or "evidence_action"),
        display_mode=str(getattr(raw_display_mode, "value", raw_display_mode) or "evidence_action"),
        match_summary=str(advice.get("match_summary") or "").strip() or None,
        why_this_matches=[
            str(item).strip()
            for item in list(advice.get("why_this_matches") or [])
            if str(item).strip()
        ][:4],
        next_best_actions=[
            str(item).strip()
            for item in list(advice.get("next_best_actions") or [])
            if str(item).strip()
        ][:4],
        validation_steps=[
            str(item).strip()
            for item in list(advice.get("validation_steps") or [])
            if str(item).strip()
        ][:3],
        base_recommended_action=str(advice.get("base_recommended_action") or "").strip() or None,
        base_next_best_actions=[
            str(item).strip()
            for item in list(advice.get("base_next_best_actions") or [])
            if str(item).strip()
        ][:4],
        base_validation_steps=[
            str(item).strip()
            for item in list(advice.get("base_validation_steps") or [])
            if str(item).strip()
        ][:3],
        action_refinement_source=str(advice.get("action_refinement_source") or "").strip() or None,
        evidence_sources=_normalized_evidence_sources(advice.get("evidence_sources")),
        llm_general_advisory=advice.get("llm_general_advisory") if isinstance(advice.get("llm_general_advisory"), dict) else None,
        created_at=created_at,
        current_feedback=None,
        feedback_summary=None,
    )


def _build_ticket_ai_recommendations(
    db: Session,
    ticket: Ticket,
    *,
    visible_tickets: list[Ticket],
    lang: str,
) -> list[RecommendationView]:
    started_at = time.perf_counter()
    try:
        details = classify_ticket_detailed(ticket.title, ticket.description, db=db, use_llm=False)
    except Exception as exc:  # noqa: BLE001
        logger.info("AI classify failed for recommendation ticket %s: %s", ticket.id, exc)
        return []

    profile = build_service_request_profile(ticket.title, ticket.description)
    routing_cross_check = validate_ticket_routing(
        title=ticket.title,
        description=ticket.description,
        classifier_details=details,
        stored_ticket_type=getattr(ticket, "ticket_type", None),
        profile=profile,
    )
    service_request_mode = routing_cross_check.use_service_request_guidance
    if service_request_mode:
        service_request_payload = build_service_request_guidance(ticket, lang=lang, enable_llm_refinement=True)
        advice = _normalize_resolution_payload(
            service_request_payload,
            default_source_label=str(service_request_payload.get("source_label") or "service_request"),
        )
        retrieval = RetrievalResult(
            query=_shared_ticket_retrieval_query(ticket, include_priority=True),
            query_context={
                "metadata": {
                    "ticket_type": "service_request",
                    "category": str(getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)) or ""),
                    "service_request_profile": service_request_payload.get("service_request_profile") or {},
                }
            },
            source="service_request",
        )
    elif routing_cross_check.routing_decision_source == "cross_check_unresolved":
        manual_reason = (
            "Les signaux de routage restent en conflit entre incident et demande de service; un triage manuel est preferable avant de proposer une recommandation."
            if lang == "fr"
            else "Routing signals still conflict between incident and service request, so manual triage is safer before showing a recommendation."
        )
        retrieval = RetrievalResult(
            query=_shared_ticket_retrieval_query(ticket, include_priority=True),
            query_context={
                "metadata": {
                    "ticket_type": str(getattr(getattr(ticket, "ticket_type", None), "value", getattr(ticket, "ticket_type", None)) or ""),
                    "category": str(getattr(getattr(ticket, "category", None), "value", getattr(ticket, "category", None)) or ""),
                    "routing_decision_source": routing_cross_check.routing_decision_source,
                    "cross_check_conflict_flag": True,
                }
            },
            source="cross_check",
        )
        advice = _normalize_resolution_payload(
            build_manual_triage_advice_payload(
                reason=manual_reason,
                lang=lang,
                source_label="cross_check",
            ),
            default_source_label="cross_check",
        )
    else:
        resolver_output = resolve_ticket_advice(
            db,
            ticket,
            visible_tickets=_candidate_tickets_for_recommendation(ticket, visible_tickets),
            top_k=5,
            solution_quality="medium",
            include_workflow=True,
            include_priority=True,
            lang=lang,
            retrieval_fn=unified_retrieve,
            advice_builder=build_resolution_advice,
        )
        retrieval = resolver_output.retrieval
        advice = _normalize_resolution_payload(
            resolution_advice_to_payload(resolver_output.advice),
            default_source_label=_normalize_line(retrieval.get("source")) or "fallback_rules",
        )
    if advice is None:
        advice = _fallback_resolution_from_classifier(details=details, retrieval=retrieval, lang=lang)
    if advice is None:
        return []

    created_at = ticket.updated_at or ticket.created_at or _utcnow()
    impact = _impact_for_ticket(ticket.priority)
    related_tickets = [ticket.id]
    action = str(advice.get("recommended_action") or "").strip()
    reasoning = str(advice.get("reasoning") or "").strip() or action
    evidence_sources = _normalized_evidence_sources(advice.get("evidence_sources"))
    similar_signal = bool(details.get("similarity_found")) or any(
        row.get("evidence_type") in {"resolved ticket", "similar ticket"} for row in evidence_sources
    )

    recs: list[RecommendationView] = []
    if similar_signal:
        description = (
            f"Des incidents similaires soutiennent cette action pour {ticket.id}. {reasoning}"
            if lang == "fr"
            else f"Similar incidents support this action for {ticket.id}. {reasoning}"
        )
        pattern_advice = _advice_with_overrides(
            advice,
            recommended_action=_pattern_recommended_action(ticket.id, advice, lang=lang),
            reasoning=description,
            next_best_actions=_pattern_next_best_actions(ticket.id, advice, lang=lang),
        )
        recs.append(
            _build_view(
                entity_prefix="ticket",
                entity_id=ticket.id,
                entity_type="ticket",
                recommendation_type=RecommendationType.pattern,
                title=(f"Pattern IA confirme pour {ticket.id}" if lang == "fr" else f"Evidence-backed pattern for {ticket.id}"),
                description=description,
                related_tickets=related_tickets,
                impact=impact,
                created_at=created_at,
                advice=pattern_advice,
                confidence_offset=0.03,
            )
        )

    suggested_priority = details.get("priority")
    if isinstance(suggested_priority, TicketPriority) and suggested_priority != ticket.priority:
        description = (
            f"Priorite actuelle: {ticket.priority.value}. Le triage recommande {suggested_priority.value}. {reasoning}"
            if lang == "fr"
            else f"Current priority: {ticket.priority.value}. Triage suggests {suggested_priority.value}. {reasoning}"
        )
        priority_advice = _advice_with_overrides(
            advice,
            recommended_action=_priority_recommended_action(
                ticket.id,
                current_priority=ticket.priority,
                suggested_priority=suggested_priority,
                lang=lang,
            ),
            reasoning=description,
            next_best_actions=_priority_next_best_actions(
                ticket.id,
                current_priority=ticket.priority,
                suggested_priority=suggested_priority,
                lang=lang,
            ),
        )
        recs.append(
            _build_view(
                entity_prefix="ticket",
                entity_id=ticket.id,
                entity_type="ticket",
                recommendation_type=RecommendationType.priority,
                title=(f"Controle de priorite pour {ticket.id}" if lang == "fr" else f"Priority check for {ticket.id}"),
                description=description,
                related_tickets=related_tickets,
                impact=RecommendationImpact.high,
                created_at=created_at,
                advice=priority_advice,
            )
        )

    recs.append(
        _build_view(
            entity_prefix="ticket",
            entity_id=ticket.id,
            entity_type="ticket",
            recommendation_type=RecommendationType.solution,
            title=(f"Solution evidence-first pour {ticket.id}" if lang == "fr" else f"Evidence-backed solution for {ticket.id}"),
            description=reasoning,
            related_tickets=related_tickets,
            impact=impact,
            created_at=created_at,
            advice=advice,
        )
    )
    if str(advice.get("display_mode") or "evidence_action") != "no_strong_match":
        workflow_description = _workflow_description(ticket.id, action, lang=lang)
        workflow_advice = _advice_with_overrides(
            advice,
            recommended_action=_workflow_recommended_action(ticket.id, action, lang=lang),
            reasoning=workflow_description,
            next_best_actions=_workflow_next_best_actions(ticket.id, action, lang=lang),
        )
        recs.append(
            _build_view(
                entity_prefix="ticket",
                entity_id=ticket.id,
                entity_type="ticket",
                recommendation_type=RecommendationType.workflow,
                title=(f"Workflow de validation pour {ticket.id}" if lang == "fr" else f"Validation workflow for {ticket.id}"),
                description=workflow_description,
                related_tickets=related_tickets,
                impact=RecommendationImpact.medium if impact == RecommendationImpact.high else impact,
                created_at=created_at,
                advice=workflow_advice,
                confidence_offset=-0.06,
            )
        )
    logger.info(
        "Recommendation ticket path: ticket=%s source=%s mode=%s elapsed_ms=%s",
        ticket.id,
        advice.get("source_label"),
        advice.get("recommendation_mode"),
        int((time.perf_counter() - started_at) * 1000),
    )
    return recs


def _problem_record_payload(
    *,
    problem: Problem,
    recommended_action: str,
    reasoning: str,
    confidence: float,
    tentative: bool,
    lang: str,
    probable_root_cause: str | None,
    evidence_excerpt: str | None,
    source_label: str = "problem_record",
    recommendation_mode: str = "evidence_grounded",
    extra_evidence: list[dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    evidence_sources = [
        {
            "evidence_type": "related problem",
            "reference": problem.id,
            "excerpt": evidence_excerpt,
        }
    ]
    for row in list(extra_evidence or []):
        reference = _normalize_line(row.get("reference"))
        if not reference or any(existing["reference"] == reference for existing in evidence_sources):
            continue
        evidence_sources.append(
            {
                "evidence_type": _normalize_line(row.get("evidence_type")),
                "reference": reference,
                "excerpt": _normalize_line(row.get("excerpt")) or None,
            }
        )
        if len(evidence_sources) >= 3:
            break
    return {
        "recommended_action": _normalize_line(recommended_action),
        "reasoning": _normalize_line(reasoning),
        "probable_root_cause": _normalize_line(probable_root_cause) or None,
        "evidence_sources": evidence_sources,
        "tentative": tentative,
        "confidence": _clamp_unit_confidence(confidence),
        "confidence_band": _confidence_band(confidence),
        "source_label": source_label,
        "recommendation_mode": "fallback_rules" if tentative else recommendation_mode,
        "action_relevance_score": _clamp_unit_confidence(0.82 if not tentative else 0.48),
        "filtered_weak_match": False,
        "display_mode": "tentative_diagnostic" if tentative else "evidence_action",
        "match_summary": (
            "Correspondance sur la cause racine documentee et les incidents lies."
            if lang == "fr"
            else "Matched on the documented root cause and linked incident pattern."
        ),
        "next_best_actions": [
            _normalize_line(recommended_action),
            (
                "Validez le resultat sur les tickets lies avant cloture."
                if lang == "fr"
                else "Validate the outcome on linked tickets before closure."
            ),
            (
                "Documentez la resolution problematique retenue."
                if lang == "fr"
                else "Document the chosen problem resolution."
            ),
        ],
    }


def _augment_problem_advice(problem: Problem, advice: dict[str, Any] | None) -> dict[str, Any] | None:
    if advice is None:
        return None
    evidence_sources = _normalized_evidence_sources(advice.get("evidence_sources"))
    if problem.root_cause and all(row["reference"] != problem.id for row in evidence_sources):
        evidence_sources.append(
            {
                "evidence_type": "related problem",
                "reference": problem.id,
                "excerpt": _normalize_line(problem.root_cause) or None,
            }
        )
    advice["evidence_sources"] = evidence_sources[:3]
    if not advice.get("probable_root_cause") and problem.root_cause:
        advice["probable_root_cause"] = _normalize_line(problem.root_cause) or None
    return advice


def _build_problem_resolution_payload(
    db: Session,
    *,
    problem: Problem,
    linked_tickets: list[Ticket],
    lang: str,
) -> dict[str, Any] | None:
    retrieval = RetrievalResult.coerce(unified_retrieve(
        db,
        query=_problem_retrieval_query(problem, linked_tickets),
        visible_tickets=linked_tickets,
        top_k=5,
        solution_quality="medium",
    ))
    advice = _augment_problem_advice(
        problem,
        _normalize_resolution_payload(
            build_resolution_advice(retrieval, lang=lang),
            default_source_label=_normalize_line(retrieval.get("source")) or "fallback_rules",
        ),
    )

    if str(problem.permanent_fix or "").strip():
        supporting = []
        if advice is not None:
            supporting = _normalized_evidence_sources(advice.get("evidence_sources"))
        reasoning = (
            f"Le correctif permanent documente sur {problem.id} reste la source la plus forte."
            if lang == "fr"
            else f"The documented permanent fix on {problem.id} remains the strongest supported action."
        )
        return _problem_record_payload(
            problem=problem,
            recommended_action=str(problem.permanent_fix).strip(),
            reasoning=reasoning,
            confidence=0.92 + (0.03 if supporting else 0.0),
            tentative=False,
            lang=lang,
            probable_root_cause=str(problem.root_cause or "").strip() or None,
            evidence_excerpt=str(problem.permanent_fix).strip(),
            extra_evidence=supporting,
        )

    primary_type = ""
    if advice and advice.get("evidence_sources"):
        primary_type = str(advice["evidence_sources"][0].get("evidence_type") or "").strip()
    if advice and primary_type in {"resolved ticket", "similar ticket", "KB article", "comment"}:
        return advice

    if str(problem.workaround or "").strip():
        reasoning = (
            f"Aucun correctif permanent valide n'est documente; utilisez le contournement de {problem.id} pour contenir l'impact."
            if lang == "fr"
            else f"No validated permanent fix is documented yet; use the {problem.id} workaround to contain impact."
        )
        return _problem_record_payload(
            problem=problem,
            recommended_action=str(problem.workaround).strip(),
            reasoning=reasoning,
            confidence=0.72,
            tentative=False,
            lang=lang,
            probable_root_cause=str(problem.root_cause or "").strip() or None,
            evidence_excerpt=str(problem.workaround).strip(),
        )

    if advice is not None:
        return advice

    if str(problem.root_cause or "").strip():
        action = (
            f"Tentative: validez la cause racine documentee sur {problem.id} avant d'appliquer un correctif plus large."
            if lang == "fr"
            else f"Tentative: validate the documented root cause on {problem.id} before applying a broader fix."
        )
        reasoning = (
            f"La meilleure evidence disponible est la cause racine documentee sur {problem.id}."
            if lang == "fr"
            else f"The strongest available evidence is the documented root cause on {problem.id}."
        )
        return _problem_record_payload(
            problem=problem,
            recommended_action=action,
            reasoning=reasoning,
            confidence=0.54,
            tentative=True,
            lang=lang,
            probable_root_cause=str(problem.root_cause).strip(),
            evidence_excerpt=str(problem.root_cause).strip(),
        )
    return None


def _build_problem_ai_recommendations(
    db: Session,
    *,
    problem: Problem,
    linked_tickets: list[Ticket],
    lang: str,
) -> list[RecommendationView]:
    if not linked_tickets:
        return []
    started_at = time.perf_counter()
    advice = _build_problem_resolution_payload(db, problem=problem, linked_tickets=linked_tickets, lang=lang)
    if advice is None:
        return []

    created_at = problem.updated_at or problem.created_at or _utcnow()
    related_ticket_ids = [ticket.id for ticket in linked_tickets][:8]
    has_critical_linked = any(ticket.priority == TicketPriority.critical and _is_active_ticket(ticket) for ticket in linked_tickets)
    impact = RecommendationImpact.high if has_critical_linked or int(problem.active_count) >= 3 else RecommendationImpact.medium
    action = str(advice.get("recommended_action") or "").strip()

    recs: list[RecommendationView] = [
        _build_view(
            entity_prefix="problem",
            entity_id=problem.id,
            entity_type="problem",
            recommendation_type=RecommendationType.pattern,
            title=(f"Pattern problematique pour {problem.id}" if lang == "fr" else f"Problem pattern for {problem.id}"),
            description=(
                f"{problem.id} regroupe {int(problem.active_count)} tickets actifs. {str(advice.get('reasoning') or action).strip()}"
                if lang == "fr"
                else f"{problem.id} groups {int(problem.active_count)} active tickets. {str(advice.get('reasoning') or action).strip()}"
            ),
            related_tickets=related_ticket_ids,
            impact=impact,
            created_at=created_at,
            advice=_advice_with_overrides(
                advice,
                recommended_action=_problem_pattern_recommended_action(problem, lang=lang),
                reasoning=(
                    f"{problem.id} regroupe {int(problem.active_count)} tickets actifs. {str(advice.get('reasoning') or action).strip()}"
                    if lang == "fr"
                    else f"{problem.id} groups {int(problem.active_count)} active tickets. {str(advice.get('reasoning') or action).strip()}"
                ),
                next_best_actions=_problem_pattern_next_best_actions(problem, lang=lang),
            ),
            confidence_offset=0.02,
        ),
        _build_view(
            entity_prefix="problem",
            entity_id=problem.id,
            entity_type="problem",
            recommendation_type=RecommendationType.solution,
            title=(f"Solution evidence-first pour {problem.id}" if lang == "fr" else f"Evidence-backed solution for {problem.id}"),
            description=str(advice.get("reasoning") or action).strip() or action,
            related_tickets=related_ticket_ids,
            impact=RecommendationImpact.high if str(problem.permanent_fix or "").strip() else impact,
            created_at=created_at,
            advice=advice,
        ),
        _build_view(
            entity_prefix="problem",
            entity_id=problem.id,
            entity_type="problem",
            recommendation_type=RecommendationType.workflow,
            title=(f"Workflow de validation pour {problem.id}" if lang == "fr" else f"Validation workflow for {problem.id}"),
            description=_workflow_description(problem.id, action, lang=lang),
            related_tickets=related_ticket_ids,
            impact=RecommendationImpact.medium,
            created_at=created_at,
            advice=_advice_with_overrides(
                advice,
                recommended_action=_problem_workflow_recommended_action(problem, lang=lang),
                reasoning=_workflow_description(problem.id, action, lang=lang),
                next_best_actions=_problem_workflow_next_best_actions(problem, action, lang=lang),
            ),
            confidence_offset=-0.06,
        ),
    ]

    if has_critical_linked:
        description = (
            f"Des incidents critiques lies restent actifs. Priorisez {problem.id} pendant l'execution de cette action."
            if lang == "fr"
            else f"Critical linked incidents are still active. Prioritize {problem.id} while executing this action."
        )
        recs.append(
            _build_view(
                entity_prefix="problem",
                entity_id=problem.id,
                entity_type="problem",
                recommendation_type=RecommendationType.priority,
                title=(f"Priorite problematique pour {problem.id}" if lang == "fr" else f"Problem priority for {problem.id}"),
                description=description,
                related_tickets=related_ticket_ids,
                impact=RecommendationImpact.high,
                created_at=created_at,
                advice=_advice_with_overrides(
                    advice,
                    recommended_action=_problem_priority_recommended_action(problem, lang=lang),
                    reasoning=description,
                    next_best_actions=_problem_priority_next_best_actions(problem, lang=lang),
                ),
            )
        )

    logger.info(
        "Recommendation problem path: problem=%s source=%s mode=%s elapsed_ms=%s",
        problem.id,
        advice.get("source_label"),
        advice.get("recommendation_mode"),
        int((time.perf_counter() - started_at) * 1000),
    )
    return recs


def _dedupe_rows(rows: list[RecommendationView]) -> list[RecommendationView]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[RecommendationView] = []
    for row in rows:
        key = (row.entity_type, row.type.value, row.title.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _attach_feedback_state(
    db: Session,
    *,
    rows: list[RecommendationView],
    user: User,
) -> list[RecommendationView]:
    if not hasattr(db, "query"):
        return rows
    bundles = get_feedback_bundles_for_recommendations(
        db,
        current_user_id=getattr(user, "id", None),
        recommendation_ids=[row.id for row in rows],
    )
    for row in rows:
        bundle = bundles.get(row.id)
        if not bundle:
            continue
        row.current_feedback = bundle.get("current_feedback")
        row.feedback_summary = bundle.get("feedback_summary")
    return rows


def list_recommendations(db: Session, user: User, *, locale: str | None = None) -> list[RecommendationView]:
    started_at = time.perf_counter()
    lang = _lang(locale)
    visible_tickets = list_tickets_for_user(db, user)
    visible_ticket_ids = {ticket.id for ticket in visible_tickets}
    if not visible_tickets:
        return _attach_feedback_state(
            db,
            rows=_legacy_recommendations(db, visible_ticket_ids=visible_ticket_ids, lang=lang),
            user=user,
        )

    ai_rows: list[RecommendationView] = []

    critical_active = [
        ticket
        for ticket in visible_tickets
        if ticket.priority == TicketPriority.critical and _is_active_ticket(ticket)
    ]
    service_request_active = [
        ticket
        for ticket in visible_tickets
        if _is_active_ticket(ticket)
        and validate_ticket_routing_for_ticket(ticket).use_service_request_guidance
    ]
    ticket_candidates: list[Ticket] = []
    seen_ticket_ids: set[str] = set()
    for ticket in sorted(
        [*critical_active, *service_request_active],
        key=lambda item: (item.updated_at or item.created_at or _utcnow()),
        reverse=True,
    ):
        ticket_id = str(getattr(ticket, "id", "") or "")
        if not ticket_id or ticket_id in seen_ticket_ids:
            continue
        seen_ticket_ids.add(ticket_id)
        ticket_candidates.append(ticket)

    for ticket in ticket_candidates[:_MAX_CRITICAL_TICKETS]:
        ai_rows.extend(
            _build_ticket_ai_recommendations(
                db,
                ticket,
                visible_tickets=visible_tickets,
                lang=lang,
            )
        )

    linked_by_problem: dict[str, list[Ticket]] = {}
    for ticket in visible_tickets:
        if ticket.problem_id:
            linked_by_problem.setdefault(ticket.problem_id, []).append(ticket)

    active_problem_count = 0
    if linked_by_problem:
        problem_ids = list(linked_by_problem.keys())
        problem_rows = (
            db.query(Problem)
            .filter(Problem.id.in_(problem_ids))
            .order_by(Problem.updated_at.desc())
            .all()
        )
        active_problems = [problem for problem in problem_rows if problem.status in _ACTIVE_PROBLEM_STATUSES]
        active_problems.sort(
            key=lambda item: (
                int(item.active_count),
                int(item.occurrences_count),
                item.updated_at or item.created_at or _utcnow(),
            ),
            reverse=True,
        )
        active_problem_count = len(active_problems[:_MAX_ACTIVE_PROBLEMS])
        for problem in active_problems[:_MAX_ACTIVE_PROBLEMS]:
            ai_rows.extend(
                _build_problem_ai_recommendations(
                    db,
                    problem=problem,
                    linked_tickets=linked_by_problem.get(problem.id, []),
                    lang=lang,
                )
            )

    ai_rows = _dedupe_rows(ai_rows)
    ai_rows.sort(
        key=lambda item: (item.created_at or _utcnow(), item.confidence),
        reverse=True,
    )
    logger.info(
        "Recommendations evidence-first path complete: tickets_considered=%s problems_considered=%s rows=%s elapsed_ms=%s",
        len(ticket_candidates[:_MAX_CRITICAL_TICKETS]),
        active_problem_count,
        len(ai_rows),
        int((time.perf_counter() - started_at) * 1000),
    )
    if ai_rows:
        return _attach_feedback_state(db, rows=ai_rows[:_MAX_RECOMMENDATIONS], user=user)
    return _attach_feedback_state(
        db,
        rows=_legacy_recommendations(db, visible_ticket_ids=visible_ticket_ids, lang=lang),
        user=user,
    )


def build_sla_strategies(db: Session, *, user: User, locale: str | None = None) -> dict[str, object]:
    tickets = list_tickets_for_user(db, user)
    return get_sla_strategies_advice(db, tickets=tickets, locale=locale)
