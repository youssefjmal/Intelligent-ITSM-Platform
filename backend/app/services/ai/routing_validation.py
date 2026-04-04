"""Cross-check validation layer for ticket recommendation routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.enums import TicketType
from app.services.ai.service_requests import (
    ServiceRequestProfile,
    build_service_request_profile,
    has_explicit_fulfillment_intent,
)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _profile_detected(profile: ServiceRequestProfile) -> bool:
    has_operation_resource = bool(profile.operation and profile.resource)
    has_operation_governance = bool(profile.operation and profile.governance)
    has_resource_governance = bool(profile.resource and profile.governance)
    return bool(profile.family or has_operation_resource or has_operation_governance or has_resource_governance)


def _profile_is_strong(profile: ServiceRequestProfile, *, explicit_intent: bool) -> bool:
    has_family = bool(profile.family)
    has_operation_resource = bool(profile.operation and profile.resource)
    has_operation_governance = bool(profile.operation and profile.governance)
    has_resource_governance = bool(profile.resource and profile.governance)
    low_incident_conflict = profile.incident_conflict_score < 1.0
    return bool(
        explicit_intent
        and low_incident_conflict
        and profile.confidence >= 0.72
        and (
            has_family
            or has_operation_resource
            or (has_operation_governance and profile.confidence >= 0.78)
            or (has_resource_governance and profile.confidence >= 0.8)
        )
    )


def _profile_is_moderate(profile: ServiceRequestProfile, *, explicit_intent: bool) -> bool:
    if profile.incident_conflict_score >= 1.0:
        return False
    if _profile_is_strong(profile, explicit_intent=explicit_intent):
        return True
    return bool(_profile_detected(profile) and explicit_intent and profile.confidence >= 0.5)


@dataclass(slots=True)
class RoutingCrossCheckResult:
    use_service_request_guidance: bool
    resolved_ticket_type: TicketType | None
    routing_decision_source: str
    cross_check_conflict_flag: bool
    cross_check_summary: str
    classifier_ticket_type: TicketType | None
    service_request_profile_detected: bool
    service_request_profile_confidence: float


def _minimal_classifier_details(*, ticket_type: Any = None, category: Any = None) -> dict[str, Any]:
    return {
        "ticket_type": None,
        "classifier_ticket_type": None,
        "category": category,
        "semantic_ticket_type": None,
        "semantic_signal_confidence": 0.0,
        "strong_match_count": 0,
    }


def validate_ticket_routing(
    *,
    title: str,
    description: str,
    classifier_details: dict[str, Any],
    stored_ticket_type: Any = None,
    profile: ServiceRequestProfile,
) -> RoutingCrossCheckResult:
    """Compare classifier, structured profile, and semantic signals before routing."""

    classifier_ticket_type = classifier_details.get("ticket_type")
    semantic_ticket_type = classifier_details.get("semantic_ticket_type")
    semantic_signal_confidence = float(classifier_details.get("semantic_signal_confidence") or 0.0)
    strong_match_count = int(classifier_details.get("strong_match_count") or 0)

    explicit_intent = has_explicit_fulfillment_intent(title, description)
    profile_detected = _profile_detected(profile)
    profile_strong = _profile_is_strong(profile, explicit_intent=explicit_intent)
    profile_moderate = _profile_is_moderate(profile, explicit_intent=explicit_intent)

    service_score = 0.0
    incident_score = 0.0
    service_support: list[str] = []
    incident_support: list[str] = []

    classifier_name = _enum_value(classifier_ticket_type)
    if classifier_name == TicketType.service_request.value:
        service_score += 1.8
        service_support.append("classifier")
    elif classifier_name == TicketType.incident.value:
        incident_score += 1.8
        incident_support.append("classifier")

    stored_name = _enum_value(stored_ticket_type)
    if stored_name == TicketType.service_request.value:
        service_score += 2.4
        service_support.append("stored_ticket")
    elif stored_name == TicketType.incident.value:
        incident_score += 2.4
        incident_support.append("stored_ticket")

    semantic_name = _enum_value(semantic_ticket_type)
    if semantic_name == TicketType.service_request.value and semantic_signal_confidence >= 0.55:
        service_score += min(2.3, 1.2 + semantic_signal_confidence)
        service_support.append(f"semantic({strong_match_count})")
    elif semantic_name == TicketType.incident.value and semantic_signal_confidence >= 0.55:
        incident_score += min(2.3, 1.2 + semantic_signal_confidence)
        incident_support.append(f"semantic({strong_match_count})")

    if profile_strong:
        service_score += 3.2
        service_support.append("service_request_profile_strong")
    elif profile_moderate:
        service_score += 2.2
        service_support.append("service_request_profile")
    elif profile_detected:
        service_score += 0.9
        service_support.append("service_request_profile_weak")

    if profile.incident_conflict_score >= 1.4:
        incident_score += min(1.6, 0.6 + (profile.incident_conflict_score / 2.0))
        incident_support.append("incident_conflict")

    conflict = bool(service_support and incident_support)

    if service_score >= incident_score + 1.0:
        if conflict and profile_strong and classifier_name == TicketType.incident.value:
            decision_source = "cross_check_profile_override"
        else:
            decision_source = service_support[0] if len(service_support) == 1 and not conflict else "cross_check_service_request"
        resolved_ticket_type = TicketType.service_request
        use_service_request_guidance = True
    elif incident_score >= service_score + 1.0 or (incident_score > service_score and not profile_moderate):
        decision_source = incident_support[0] if len(incident_support) == 1 and not conflict else "cross_check_incident"
        resolved_ticket_type = TicketType.incident if classifier_name or semantic_name or stored_name else None
        use_service_request_guidance = False
    elif profile_strong or (profile_moderate and service_score >= incident_score):
        conflict = bool(conflict or incident_support)
        decision_source = "cross_check_profile_override"
        resolved_ticket_type = TicketType.service_request
        use_service_request_guidance = True
    else:
        conflict = True
        decision_source = "cross_check_unresolved"
        resolved_ticket_type = TicketType.incident if incident_score > 0.0 else classifier_ticket_type
        use_service_request_guidance = False

    agreement = service_support if use_service_request_guidance else incident_support
    disagreement = incident_support if use_service_request_guidance else service_support
    winner_label = "service_request" if use_service_request_guidance else "incident"
    agreement_text = ", ".join(agreement) if agreement else "no dominant component"
    disagreement_text = ", ".join(disagreement) if disagreement else "none"
    summary = (
        f"Routing selected {winner_label} via {decision_source}; "
        f"agreeing signals: {agreement_text}; disagreeing signals: {disagreement_text}; "
        f"profile_confidence={round(float(profile.confidence or 0.0), 4)}."
    )

    return RoutingCrossCheckResult(
        use_service_request_guidance=use_service_request_guidance,
        resolved_ticket_type=resolved_ticket_type,
        routing_decision_source=decision_source,
        cross_check_conflict_flag=conflict,
        cross_check_summary=summary,
        classifier_ticket_type=classifier_ticket_type,
        service_request_profile_detected=profile_detected,
        service_request_profile_confidence=round(max(0.0, float(profile.confidence or 0.0)), 4),
    )


def validate_ticket_routing_for_ticket(
    ticket: Any,
    *,
    classifier_details: dict[str, Any] | None = None,
    db: Any = None,
) -> RoutingCrossCheckResult:
    """Run the routing cross-check directly against a ticket-like object.

    If classifier details are not provided, the function falls back to the
    stored ticket_type/category signals so consumers can reuse the same routing
    logic without forcing a full semantic classification pass.
    """

    title = str(getattr(ticket, "title", "") or "")
    description = str(getattr(ticket, "description", "") or "")
    stored_ticket_type = getattr(ticket, "ticket_type", None)
    stored_category = getattr(ticket, "category", None)
    details = classifier_details
    if details is None and db is not None:
        try:
            from app.services.ai.classifier import classify_ticket_detailed

            details = classify_ticket_detailed(title, description, db=db, use_llm=False)
        except Exception:
            details = None
    if details is None:
        details = _minimal_classifier_details(ticket_type=stored_ticket_type, category=stored_category)
    profile = build_service_request_profile(title, description)
    return validate_ticket_routing(
        title=title,
        description=description,
        classifier_details=details,
        stored_ticket_type=stored_ticket_type,
        profile=profile,
    )
