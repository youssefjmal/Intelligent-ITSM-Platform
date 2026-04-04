"""Shared service-request guidance helpers.

Service requests are planned fulfillment workflows, not incident-diagnostic
flows. This module centralizes how we:

1. detect service-request tickets from structured ticket metadata, and
2. build fulfillment-oriented AI guidance without root-cause language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.models.enums import TicketCategory, TicketType
from app.services.ai.calibration import confidence_band
from app.services.ai.topic_templates import (
    topic_service_request_actions,
    topic_service_request_validation,
)
from app.services.ai.taxonomy import (
    SERVICE_REQUEST_FAMILY_HINTS,
    SERVICE_REQUEST_GOVERNANCE_HINTS,
    SERVICE_REQUEST_HINT_VOCAB,
    SERVICE_REQUEST_INCIDENT_CONFLICT_HINTS,
    SERVICE_REQUEST_OPERATION_HINTS,
    SERVICE_REQUEST_RESOURCE_HINTS,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)
_PROFILE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "please",
        "team",
        "teams",
        "expected",
        "current",
        "ticket",
        "task",
        "tasks",
        "request",
        "requests",
        "workflow",
        "service",
        "services",
        "approved",
        "owner",
        "responsible",
        "before",
        "after",
        "using",
        "create",
        "grant",
        "rotate",
        "update",
        "schedule",
    }
)
_TARGET_TERM_LIMIT = 6
_TITLE_MATCH_BONUS = 0.35
_PHRASE_LENGTH_BONUS = 0.2
_INTENT_PREFIX_LIMIT = 4
_SERVICE_REQUEST_HINT_TOKENS = frozenset(
    token
    for phrase in SERVICE_REQUEST_HINT_VOCAB
    for token in _TOKEN_RE.findall(str(phrase).casefold())
)


@dataclass(slots=True)
class ServiceRequestProfile:
    family: str | None = None
    family_scores: dict[str, float] = field(default_factory=dict)
    operation: str | None = None
    operation_scores: dict[str, float] = field(default_factory=dict)
    resource: str | None = None
    resource_scores: dict[str, float] = field(default_factory=dict)
    governance: tuple[str, ...] = ()
    governance_scores: dict[str, float] = field(default_factory=dict)
    target_terms: tuple[str, ...] = ()
    incident_conflict_score: float = 0.0
    confidence: float = 0.0

    def as_metadata(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "operation": self.operation,
            "resource": self.resource,
            "governance": list(self.governance),
            "target_terms": list(self.target_terms),
            "incident_conflict_score": self.incident_conflict_score,
            "confidence": self.confidence,
        }


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _signal_tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(text or "")]


def _token_sequence_present(tokens: list[str], phrase_tokens: tuple[str, ...]) -> bool:
    if not phrase_tokens:
        return False
    if len(phrase_tokens) == 1:
        return phrase_tokens[0] in set(tokens)
    max_start = len(tokens) - len(phrase_tokens) + 1
    if max_start <= 0:
        return False
    for start in range(max_start):
        if tuple(tokens[start : start + len(phrase_tokens)]) == phrase_tokens:
            return True
    return False


def _hint_scores(
    title_tokens: list[str],
    tokens: list[str],
    hint_map: dict[str, frozenset[str]],
) -> dict[str, float]:
    if not tokens:
        return {}
    scores: dict[str, float] = {}
    for label, hints in hint_map.items():
        score = 0.0
        for phrase in hints:
            phrase_tokens = tuple(_signal_tokens(str(phrase)))
            if not phrase_tokens:
                continue
            if _token_sequence_present(tokens, phrase_tokens):
                weight = 1.0 + (_PHRASE_LENGTH_BONUS * max(0, len(phrase_tokens) - 1))
                score += weight
                if _token_sequence_present(title_tokens, phrase_tokens):
                    score += _TITLE_MATCH_BONUS
        if score > 0.0:
            scores[label] = round(score, 4)
    return scores


def _best_scored_label(
    scores: dict[str, float],
    *,
    minimum: float,
    margin: float,
) -> str | None:
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    top_label, top_score = ranked[0]
    second_score = float(ranked[1][1]) if len(ranked) > 1 else 0.0
    if top_score >= max(minimum, second_score + margin):
        return top_label
    return None


def _active_labels(
    scores: dict[str, float],
    *,
    minimum: float,
) -> tuple[str, ...]:
    return tuple(
        label
        for label, score in sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        if float(score) >= minimum
    )


def _profile_target_terms(title_tokens: list[str], tokens: list[str]) -> tuple[str, ...]:
    ordered_tokens = [*title_tokens, *tokens]
    unique: list[str] = []
    seen: set[str] = set()
    for token in ordered_tokens:
        normalized = token.casefold()
        if (
            len(normalized) < 3
            or normalized in seen
            or normalized in _PROFILE_STOPWORDS
            or normalized in _SERVICE_REQUEST_HINT_TOKENS
            or normalized.isdigit()
        ):
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) >= _TARGET_TERM_LIMIT:
            break
    return tuple(unique)


def _operation_hint_at_start(tokens: list[str]) -> bool:
    if not tokens:
        return False
    prefix = tokens[:_INTENT_PREFIX_LIMIT]
    for hints in SERVICE_REQUEST_OPERATION_HINTS.values():
        for phrase in hints:
            phrase_tokens = tuple(_signal_tokens(str(phrase)))
            if not phrase_tokens:
                continue
            if tuple(prefix[: len(phrase_tokens)]) == phrase_tokens:
                return True
    return False


def has_explicit_fulfillment_intent(title: str, description: str) -> bool:
    """Return True when the ticket text explicitly asks for planned work."""

    return _operation_hint_at_start(_signal_tokens(title)) or _operation_hint_at_start(_signal_tokens(description))


def _profile_confidence(
    *,
    family: str | None,
    family_scores: dict[str, float],
    operation: str | None,
    resource: str | None,
    governance: tuple[str, ...],
    target_terms: tuple[str, ...],
    incident_conflict_score: float,
) -> float:
    top_family_score = max((float(value) for value in family_scores.values()), default=0.0)
    score = 0.0
    if family:
        score += 0.42
    score += min(0.22, top_family_score / 8.0)
    if operation:
        score += 0.12
    if resource:
        score += 0.14
    score += min(0.16, 0.04 * len(governance))
    score += min(0.12, 0.03 * len(target_terms))
    score -= min(0.36, incident_conflict_score / 4.0)
    return round(min(score, 0.94), 4)


def _conflict_score(
    title_tokens: list[str],
    tokens: list[str],
    hints: frozenset[str],
) -> float:
    if not tokens or not hints:
        return 0.0
    score = 0.0
    for phrase in hints:
        phrase_tokens = tuple(_signal_tokens(str(phrase)))
        if not phrase_tokens:
            continue
        if _token_sequence_present(tokens, phrase_tokens):
            weight = 1.0 + (_PHRASE_LENGTH_BONUS * max(0, len(phrase_tokens) - 1))
            score += weight
            if _token_sequence_present(title_tokens, phrase_tokens):
                score += _TITLE_MATCH_BONUS
    return round(score, 4)


def build_service_request_profile(title: str, description: str) -> ServiceRequestProfile:
    text = _normalize_text(f"{title} {description}")
    title_tokens = _signal_tokens(title)
    tokens = _signal_tokens(text)
    if not tokens:
        return ServiceRequestProfile()

    family_scores = _hint_scores(title_tokens, tokens, SERVICE_REQUEST_FAMILY_HINTS)
    operation_scores = _hint_scores(title_tokens, tokens, SERVICE_REQUEST_OPERATION_HINTS)
    resource_scores = _hint_scores(title_tokens, tokens, SERVICE_REQUEST_RESOURCE_HINTS)
    governance_scores = _hint_scores(title_tokens, tokens, SERVICE_REQUEST_GOVERNANCE_HINTS)

    family = _best_scored_label(family_scores, minimum=1.0, margin=0.35)
    operation = _best_scored_label(operation_scores, minimum=1.0, margin=0.15)
    resource = _best_scored_label(resource_scores, minimum=1.0, margin=0.15)
    governance = _active_labels(governance_scores, minimum=1.0)
    target_terms = _profile_target_terms(title_tokens, tokens)
    incident_conflict_score = _conflict_score(
        title_tokens,
        tokens,
        SERVICE_REQUEST_INCIDENT_CONFLICT_HINTS,
    )
    confidence = _profile_confidence(
        family=family,
        family_scores=family_scores,
        operation=operation,
        resource=resource,
        governance=governance,
        target_terms=target_terms,
        incident_conflict_score=incident_conflict_score,
    )
    return ServiceRequestProfile(
        family=family,
        family_scores=family_scores,
        operation=operation,
        operation_scores=operation_scores,
        resource=resource,
        resource_scores=resource_scores,
        governance=governance,
        governance_scores=governance_scores,
        target_terms=target_terms,
        incident_conflict_score=incident_conflict_score,
        confidence=confidence,
    )


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = left & right
    if not overlap:
        return 0.0
    return len(overlap) / max(1, min(len(left), len(right)))


def service_request_profile_similarity(
    base: ServiceRequestProfile,
    candidate: ServiceRequestProfile,
) -> float:
    score = 0.0
    if base.family and candidate.family:
        if base.family == candidate.family:
            score += 0.48
        else:
            score += 0.04
    if base.operation and candidate.operation and base.operation == candidate.operation:
        score += 0.18
    if base.resource and candidate.resource and base.resource == candidate.resource:
        score += 0.18
    score += 0.10 * _overlap_ratio(set(base.governance), set(candidate.governance))
    score += 0.06 * _overlap_ratio(set(base.target_terms), set(candidate.target_terms))
    if base.family and candidate.family and base.family != candidate.family:
        score *= 0.6
    return round(min(score, 1.0), 4)


def service_request_profile_from_ticket(ticket: Any) -> ServiceRequestProfile:
    return build_service_request_profile(
        _normalize_text(getattr(ticket, "title", "")),
        _normalize_text(getattr(ticket, "description", "")),
    )


def is_service_request_like(
    *,
    ticket_type: Any = None,
    category: Any = None,
) -> bool:
    """Return True when structured ticket signals indicate a service request."""

    ticket_type_name = _enum_value(ticket_type)
    category_name = _enum_value(category)
    if ticket_type_name == TicketType.service_request.value:
        return True
    if ticket_type_name in {TicketType.incident.value, "incident"}:
        return False
    return category_name == TicketCategory.service_request.value


def should_use_service_request_guidance(
    title: str,
    description: str,
    *,
    ticket_type: Any = None,
    category: Any = None,
) -> bool:
    """Return True when fulfillment/runbook guidance should replace incident diagnosis."""

    profile = build_service_request_profile(title, description)
    explicit_intent = has_explicit_fulfillment_intent(title, description)
    has_family = bool(profile.family)
    has_operation_resource = bool(profile.operation and profile.resource)
    has_operation_governance = bool(profile.operation and profile.governance)
    has_resource_governance = bool(profile.resource and profile.governance)
    structured_profile = has_family or has_operation_resource
    low_incident_conflict = profile.incident_conflict_score < 1.0
    ticket_type_name = _enum_value(ticket_type)
    category_name = _enum_value(category)
    strong_profile_override = (
        explicit_intent
        and
        low_incident_conflict
        and profile.confidence >= 0.72
        and (
            has_family
            or has_operation_resource
            or (has_operation_governance and profile.confidence >= 0.78)
            or (has_resource_governance and profile.confidence >= 0.8)
        )
    )
    if ticket_type_name == TicketType.incident.value and not strong_profile_override:
        return False

    if is_service_request_like(ticket_type=ticket_type, category=category):
        if has_family:
            return low_incident_conflict
        if has_operation_resource:
            return low_incident_conflict
        if has_operation_governance and profile.confidence >= 0.28:
            return low_incident_conflict
        if has_resource_governance and profile.confidence >= 0.32:
            return low_incident_conflict
        return (
            category_name == TicketCategory.service_request.value
            and profile.confidence >= 0.35
            and low_incident_conflict
        )

    if not (structured_profile or has_operation_governance or has_resource_governance) or not low_incident_conflict:
        return False
    if has_family and profile.confidence >= 0.5:
        return True
    if has_operation_resource and profile.confidence >= 0.44:
        return True
    return (
        (has_resource_governance or has_operation_governance)
        and profile.confidence >= 0.52
    )


def service_request_topic_scores(title: str, description: str) -> dict[str, float]:
    return dict(build_service_request_profile(title, description).family_scores)


def dominant_service_request_topic(title: str, description: str) -> str | None:
    return build_service_request_profile(title, description).family


def _guidance_confidence(profile: ServiceRequestProfile) -> float:
    confidence = 0.58
    if profile.family:
        confidence += 0.12
    if profile.operation:
        confidence += 0.05
    if profile.resource:
        confidence += 0.05
    confidence += min(0.09, 0.03 * len(profile.governance))
    confidence += min(0.06, 0.03 * len(profile.target_terms[:2]))
    return round(min(confidence, 0.9), 4)


def _profile_reasoning(profile: ServiceRequestProfile, *, lang: str) -> str:
    family_label = profile.family.replace("_", " ") if profile.family else None
    facet_bits = [
        label.replace("_", " ")
        for label in [profile.operation, profile.resource]
        if label
    ]
    if lang == "en":
        if family_label and facet_bits:
            return (
                f"This ticket aligns with the {family_label} fulfillment workflow"
                f" and the extracted request profile ({', '.join(facet_bits)}),"
                " so the AI returns runbook guidance instead of incident diagnosis."
            )
        if family_label:
            return (
                f"This ticket aligns with the {family_label} fulfillment workflow,"
                " so the AI returns runbook guidance instead of incident diagnosis."
            )
        return (
            "This ticket aligns with a planned fulfillment workflow,"
            " so the AI returns runbook guidance instead of incident diagnosis."
        )
    if family_label and facet_bits:
        return (
            f"Ce ticket correspond au workflow de fulfilment {family_label}"
            f" et au profil de demande extrait ({', '.join(facet_bits)}),"
            " donc l'IA renvoie un guidage de runbook plutot qu'un diagnostic d'incident."
        )
    if family_label:
        return (
            f"Ce ticket correspond au workflow de fulfilment {family_label},"
            " donc l'IA renvoie un guidage de runbook plutot qu'un diagnostic d'incident."
        )
    return (
        "Ce ticket correspond a un workflow planifie de fulfilment,"
        " donc l'IA renvoie un guidage de runbook plutot qu'un diagnostic d'incident."
    )


def _profile_match_summary(profile: ServiceRequestProfile, *, lang: str) -> str:
    if profile.family:
        label = profile.family.replace("_", " ")
        return (
            f"Matched on the {label} fulfillment workflow."
            if lang == "en"
            else f"Correspondance avec le workflow de fulfilment {label}."
        )
    return (
        "Matched on a planned fulfillment workflow."
        if lang == "en"
        else "Correspondance avec un workflow planifie de fulfilment."
    )


def _profile_why_this_matches(profile: ServiceRequestProfile, *, lang: str) -> list[str]:
    rows = [
        (
            "The ticket language describes a planned task rather than an active system failure."
            if lang == "en"
            else "Le texte du ticket decrit une tache planifiee plutot qu'une panne active."
        )
    ]
    if profile.family:
        family_label = profile.family.replace("_", " ")
        rows.append(
            (
                f"Structured request signals align with the {family_label} workflow family."
                if lang == "en"
                else f"Les signaux structures de demande s'alignent avec la famille de workflow {family_label}."
            )
        )
    if profile.operation or profile.resource:
        facets = " / ".join(
            label.replace("_", " ")
            for label in [profile.operation, profile.resource]
            if label
        )
        rows.append(
            (
                f"Extracted request profile: {facets}."
                if lang == "en"
                else f"Profil de demande extrait : {facets}."
            )
        )
    rows.append(
        (
            "Root-cause and remediation evidence are intentionally suppressed for service-request guidance."
            if lang == "en"
            else "Les sections cause racine et remediations incident sont volontairement supprimees pour une demande de service."
        )
    )
    return rows[:4]


def build_service_request_guidance(
    ticket: Any,
    *,
    lang: str = "fr",
    enable_llm_refinement: bool = False,
) -> dict[str, Any]:
    """Build fulfillment-oriented AI guidance for service requests."""

    title = _normalize_text(getattr(ticket, "title", ""))
    description = _normalize_text(getattr(ticket, "description", ""))
    profile = build_service_request_profile(title, description)
    topic = profile.family

    actions = topic_service_request_actions(topic, lang=lang)
    if not actions:
        actions = [
            (
                "Confirm the request scope, owner, and prerequisites before executing the task."
                if lang == "en"
                else "Confirmez le perimetre, le responsable et les prerequis avant d'executer la tache."
            ),
            (
                "Execute the planned request using the documented workflow and capture the outcome on the ticket."
                if lang == "en"
                else "Executez la demande planifiee selon le workflow documente et consignez le resultat sur le ticket."
            ),
            (
                "Notify the requester or owning team once the task is completed and verified."
                if lang == "en"
                else "Notifiez le demandeur ou l'equipe responsable une fois la tache terminee et verifiee."
            ),
        ]
    base_recommended_action = actions[0]
    base_next_best_actions = actions[1:]
    validation_step = topic_service_request_validation(topic, lang=lang)
    base_validation_steps = [validation_step] if validation_step else []
    if validation_step:
        base_next_best_actions.append(validation_step)

    recommended_action = base_recommended_action
    next_best_actions = list(base_next_best_actions)
    validation_steps = list(base_validation_steps)
    action_refinement_source = "none"

    if enable_llm_refinement:
        try:
            from app.services.ai.action_refiner import refine_service_request_actions

            refined = refine_service_request_actions(
                ticket_title=title,
                ticket_description=description,
                profile_metadata=profile.as_metadata(),
                base_recommended_action=base_recommended_action,
                base_next_best_actions=base_next_best_actions,
                base_validation_steps=base_validation_steps,
                language=lang,
            )
        except Exception:  # noqa: BLE001
            refined = None
        if refined is not None:
            recommended_action = refined.recommended_action
            next_best_actions = list(refined.next_best_actions)
            validation_steps = list(refined.validation_steps)
            action_refinement_source = "service_request_llm"

    confidence = _guidance_confidence(profile)
    confidence_band_label = confidence_band(confidence)
    reasoning = _profile_reasoning(profile, lang=lang)
    match_summary = _profile_match_summary(profile, lang=lang)
    why_this_matches = _profile_why_this_matches(profile, lang=lang)
    response_text = (
        (
            f"Service request guidance: {recommended_action}"
            if lang == "en"
            else f"Guidage de demande de service : {recommended_action}"
        )
    )
    workflow_steps = [recommended_action, *next_best_actions[:3]]
    return {
        "response_type": "service_request_advice",
        "service_request_profile": profile.as_metadata(),
        "recommended_action": recommended_action,
        "reasoning": reasoning,
        "probable_root_cause": None,
        "root_cause": None,
        "supporting_context": None,
        "why_this_matches": why_this_matches,
        "evidence_sources": [],
        "tentative": False,
        "confidence": confidence,
        "confidence_band": confidence_band_label,
        "confidence_label": confidence_band_label,
        "source_label": "service_request",
        "recommendation_mode": "service_request",
        "action_relevance_score": round(min(0.92, 0.72 + (0.18 if topic else 0.08) + (0.04 if profile.resource else 0.0)), 4),
        "filtered_weak_match": False,
        "mode": "service_request",
        "display_mode": "service_request",
        "match_summary": match_summary,
        "next_best_actions": next_best_actions[:4],
        "base_recommended_action": base_recommended_action,
        "base_next_best_actions": base_next_best_actions[:4],
        "base_validation_steps": base_validation_steps[:3],
        "action_refinement_source": action_refinement_source,
        "workflow_steps": workflow_steps[:4],
        "validation_steps": validation_steps,
        "fallback_action": recommended_action,
        "missing_information": [],
        "response_text": response_text,
        "knowledge_source": None,
    }
