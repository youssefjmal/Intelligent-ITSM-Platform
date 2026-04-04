from __future__ import annotations

from app.models.enums import TicketCategory, TicketPriority, TicketType
from app.services.ai.routing_validation import validate_ticket_routing
from app.services.ai.service_requests import build_service_request_profile


def _details(
    *,
    ticket_type,
    category=TicketCategory.application,
    semantic_ticket_type=None,
    semantic_confidence=0.0,
    strong_match_count=0,
):
    return {
        "priority": TicketPriority.medium,
        "ticket_type": ticket_type,
        "classifier_ticket_type": ticket_type,
        "category": category,
        "semantic_ticket_type": semantic_ticket_type,
        "semantic_signal_confidence": semantic_confidence,
        "strong_match_count": strong_match_count,
    }


def test_routing_cross_check_prefers_agreed_service_request_signals() -> None:
    profile = build_service_request_profile(
        "Provision service account for the SFTP import job",
        "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
    )

    result = validate_ticket_routing(
        title="Provision service account for the SFTP import job",
        description="Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
        classifier_details=_details(
            ticket_type=TicketType.service_request,
            category=TicketCategory.service_request,
            semantic_ticket_type=TicketType.service_request,
            semantic_confidence=0.74,
            strong_match_count=2,
        ),
        stored_ticket_type=TicketType.service_request,
        profile=profile,
    )

    assert result.use_service_request_guidance is True
    assert result.resolved_ticket_type == TicketType.service_request
    assert result.cross_check_conflict_flag is False


def test_routing_cross_check_overrides_contextual_incident_classifier_with_strong_profile() -> None:
    profile = build_service_request_profile(
        "Create distribution list for the ops war room",
        "Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
    )

    result = validate_ticket_routing(
        title="Create distribution list for the ops war room",
        description="Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
        classifier_details=_details(
            ticket_type=TicketType.incident,
            category=TicketCategory.email,
            semantic_ticket_type=TicketType.incident,
            semantic_confidence=0.0,
        ),
        stored_ticket_type=None,
        profile=profile,
    )

    assert result.use_service_request_guidance is True
    assert result.resolved_ticket_type == TicketType.service_request
    assert result.cross_check_conflict_flag is True
    assert result.routing_decision_source == "cross_check_profile_override"
    assert "disagreeing signals" in result.cross_check_summary


def test_routing_cross_check_marks_unresolved_conflict_when_incident_signals_win() -> None:
    profile = build_service_request_profile(
        "Update access wording in the onboarding form",
        "Update the onboarding form wording and confirm the new approval text with HR.",
    )

    result = validate_ticket_routing(
        title="Update access wording in the onboarding form",
        description="Update the onboarding form wording and confirm the new approval text with HR.",
        classifier_details=_details(
            ticket_type=TicketType.incident,
            category=TicketCategory.application,
            semantic_ticket_type=TicketType.incident,
            semantic_confidence=0.82,
            strong_match_count=3,
        ),
        stored_ticket_type=None,
        profile=profile,
    )

    assert result.use_service_request_guidance is False
    assert result.cross_check_conflict_flag is True
    assert result.routing_decision_source in {"cross_check_incident", "cross_check_unresolved"}
