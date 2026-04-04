"""Tests for service request routing bypass and taxonomy contamination guards."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.schemas.ai import UnknownTicketType
from app.services.ai.classifier import infer_ticket_type
from app.services.ai.resolver import candidate_tickets_for_ticket
from app.services.ai.service_requests import (
    build_service_request_guidance,
    build_service_request_profile,
    dominant_service_request_topic,
    service_request_profile_similarity,
    should_use_service_request_guidance,
)
from app.services.ai.taxonomy import CATEGORY_HINTS, SERVICE_REQUEST_FAMILY_HINTS, TOPIC_HINTS
from app.models.enums import TicketCategory, TicketType


# ---------------------------------------------------------------------------
# infer_ticket_type — fallback now returns None instead of TicketType.incident
# ---------------------------------------------------------------------------


def test_infer_ticket_type_returns_structured_unknown_for_ambiguous_text() -> None:
    """No strong signals → returns None (manual triage required)."""
    result = infer_ticket_type("Something happened", "Not sure what is going on")
    assert isinstance(result, UnknownTicketType)
    assert result.requires_manual_triage is True
    assert result.reason == "no_strong_signal"


def test_infer_ticket_type_detects_service_request_keywords() -> None:
    result = infer_ticket_type("New account request", "Please create an account for the new hire")
    assert result == TicketType.service_request


def test_infer_ticket_type_detects_incident_keywords() -> None:
    result = infer_ticket_type("Server is down", "Production is broken, users cannot log in")
    assert result == TicketType.incident


def test_infer_ticket_type_permission_denied_is_incident_not_sr() -> None:
    """'permission denied' is an access error (incident), not a service request.
    Regression: old code matched 'permission' as a service_request keyword before
    checking incident signals, so this returned service_request."""
    result = infer_ticket_type(
        "Legal archive access returns permission denied",
        "The legal share can open the archive root, but all protected folders underneath return permission denied for authorised users.",
    )
    assert result == TicketType.incident


def test_infer_ticket_type_incident_wins_over_sr_when_both_match() -> None:
    """When both incident and service-request signals are present the incident
    classification takes priority — something breaking > something being requested."""
    result = infer_ticket_type(
        "Access request failing with error",
        "The access request form returns an error and users cannot submit it.",
    )
    assert result == TicketType.incident


def test_infer_ticket_type_install_failed_is_incident_not_service_request() -> None:
    result = infer_ticket_type(
        "CRM install failed after package update",
        "The installation failed with an authentication error and users cannot continue.",
    )
    assert result == TicketType.incident


def test_infer_ticket_type_treats_contextual_incident_noun_as_service_request() -> None:
    result = infer_ticket_type(
        "Create distribution list for the ops war room",
        "Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
        category=TicketCategory.email,
    )
    assert result == TicketType.service_request


def test_infer_ticket_type_uses_service_request_category_hint() -> None:
    result = infer_ticket_type(
        "Something",
        "Something",
        category=TicketCategory.service_request,
    )
    assert result == TicketType.service_request


def test_infer_ticket_type_preserves_current_when_no_signals() -> None:
    result = infer_ticket_type(
        "Ambiguous title",
        "Ambiguous description with no strong signals",
        current=TicketType.incident,
    )
    assert result == TicketType.incident


# ---------------------------------------------------------------------------
# Taxonomy — webhook_rotation and scheduled_maintenance topic families
# ---------------------------------------------------------------------------


def test_webhook_rotation_topic_family_exists() -> None:
    assert "webhook_rotation" in TOPIC_HINTS, "webhook_rotation topic family missing from TOPIC_HINTS"


def test_scheduled_maintenance_topic_family_exists() -> None:
    assert "scheduled_maintenance" in TOPIC_HINTS, "scheduled_maintenance topic family missing from TOPIC_HINTS"


def test_webhook_rotation_keywords_present() -> None:
    hints = TOPIC_HINTS["webhook_rotation"]
    assert "webhook" in hints
    assert "rotate token" in hints


def test_scheduled_maintenance_keywords_present() -> None:
    hints = TOPIC_HINTS["scheduled_maintenance"]
    assert "cron job" in hints
    assert "scheduled maintenance" in hints


def test_service_request_category_hints_include_webhook() -> None:
    hints = CATEGORY_HINTS.get("service_request", frozenset())
    # At least one webhook-related term should be present
    webhook_terms = {"webhook rotation", "secret rotation"}
    assert hints & webhook_terms, (
        f"service_request CATEGORY_HINTS should include webhook/rotation terms; got {hints}"
    )


def test_service_request_guidance_uses_webhook_rotation_family() -> None:
    guidance = build_service_request_guidance(
        type(
            "TicketLike",
            (),
            {
                "title": "Create webhook rotation reminder task",
                "description": "Create a recurring reminder task to update the webhook secret on the approved cadence.",
            },
        )(),
        lang="en",
    )

    assert dominant_service_request_topic(
        "Create webhook rotation reminder task",
        "Create a recurring reminder task to update the webhook secret on the approved cadence.",
    ) == "scheduled_maintenance"
    assert guidance["display_mode"] == "service_request"
    assert guidance["recommendation_mode"] == "service_request"
    assert guidance["recommended_action"]
    assert guidance["probable_root_cause"] is None


def test_service_request_family_registry_contains_generic_fulfillment_families() -> None:
    assert "account_provisioning" in SERVICE_REQUEST_FAMILY_HINTS
    assert "access_provisioning" in SERVICE_REQUEST_FAMILY_HINTS
    assert "credential_rotation" in SERVICE_REQUEST_FAMILY_HINTS
    assert "notification_distribution_change" in SERVICE_REQUEST_FAMILY_HINTS


def test_service_request_profile_extracts_account_provisioning_facets() -> None:
    profile = build_service_request_profile(
        "Provision service account for the SFTP import job",
        "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
    )

    assert profile.family == "account_provisioning"
    assert profile.operation == "create"
    assert profile.resource == "account"
    assert "policy" in profile.governance
    assert "sftp" in profile.target_terms
    assert profile.confidence > 0.6


def test_service_request_profile_extracts_reporting_workspace_setup_facets() -> None:
    profile = build_service_request_profile(
        "Build a SLA dashboard for the weekly review",
        "Build a dashboard for the weekly SLA review with widgets for due tickets, breached SLA, and ticket aging.",
    )

    assert profile.family == "reporting_workspace_setup"
    assert profile.operation == "create"
    assert profile.resource == "workspace"
    assert profile.confidence > 0.6


def test_service_request_profile_extracts_device_provisioning_facets() -> None:
    profile = build_service_request_profile(
        "Provision a mobile hotspot for a field engineer",
        "Prepare a mobile hotspot for the field engineer and activate the approved roaming profile before the site visit.",
    )

    assert profile.family == "device_provisioning"
    assert profile.operation == "create"
    assert profile.resource == "device"
    assert profile.confidence > 0.6


def test_service_request_guidance_detects_planned_dashboard_workflow_even_when_category_is_application() -> None:
    assert should_use_service_request_guidance(
        "Build a SLA dashboard for the weekly review",
        "Build a dashboard for the weekly SLA review with widgets for due tickets, breached SLA, and ticket aging.",
        ticket_type=None,
        category=TicketCategory.application,
    ) is True


def test_service_request_guidance_detects_device_provisioning_even_when_type_is_unknown() -> None:
    assert should_use_service_request_guidance(
        "Provision a mobile hotspot for a field engineer",
        "Prepare a mobile hotspot for the field engineer and activate the approved roaming profile before the site visit.",
        ticket_type=None,
        category=TicketCategory.hardware,
    ) is True


def test_service_request_guidance_accepts_operation_plus_governance_for_existing_service_requests() -> None:
    assert should_use_service_request_guidance(
        "Increase storage quota for the legal archive share",
        "Increase the approved storage quota for the legal archive share and confirm the final allocation with the requester.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.infrastructure,
    ) is True


def test_service_request_guidance_accepts_resource_plus_governance_for_existing_service_requests() -> None:
    assert should_use_service_request_guidance(
        "Add approved members to the procurement workspace",
        "Add the approved members to the procurement workspace and confirm inherited document access.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
    ) is True


def test_service_request_guidance_can_override_contextual_incident_label_for_distribution_request() -> None:
    assert should_use_service_request_guidance(
        "Create distribution list for the ops war room",
        "Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
        ticket_type=TicketType.incident,
        category=TicketCategory.email,
    ) is True


def test_service_request_guidance_does_not_override_true_application_incident() -> None:
    assert should_use_service_request_guidance(
        "Export button now returns an application error",
        "Finance analysts can load the dashboard, but the export button now returns an application error after last night's patch.",
        ticket_type=TicketType.incident,
        category=TicketCategory.application,
    ) is False


def test_service_request_guidance_uses_provisioning_family_for_service_account_request() -> None:
    guidance = build_service_request_guidance(
        type(
            "TicketLike",
            (),
            {
                "title": "Provision service account for the SFTP import job",
                "description": "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
            },
        )(),
        lang="en",
    )

    assert dominant_service_request_topic(
        "Provision service account for the SFTP import job",
        "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
    ) == "account_provisioning"
    assert guidance["display_mode"] == "service_request"
    assert "account" in guidance["recommended_action"].lower()
    assert guidance["validation_steps"]


def test_service_request_profile_similarity_prefers_same_family() -> None:
    base = build_service_request_profile(
        "Provision service account for the SFTP import job",
        "Create a service account for the nightly SFTP import job and apply the approved policy.",
    )
    same_family = build_service_request_profile(
        "Create shared mailbox account for finance notifications",
        "Provision a shared mailbox account with the approved owner and validation checklist.",
    )
    different_family = build_service_request_profile(
        "Create webhook rotation reminder task",
        "Create a recurring reminder task to update the webhook secret on the approved cadence.",
    )

    assert service_request_profile_similarity(base, same_family) > service_request_profile_similarity(base, different_family)


def test_candidate_tickets_for_ticket_prefers_same_service_request_family() -> None:
    base = SimpleNamespace(
        id="TW-SR-BASE",
        title="Provision service account for the SFTP import job",
        description="Create a service account for the nightly SFTP import job and apply the approved policy.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        problem_id=None,
    )
    same_family = SimpleNamespace(
        id="TW-SR-ACCOUNT",
        title="Create shared mailbox account for finance notifications",
        description="Provision a shared mailbox account with the approved owner and validation checklist.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        problem_id=None,
    )
    different_family = SimpleNamespace(
        id="TW-SR-WEBHOOK",
        title="Create webhook rotation reminder task",
        description="Create a recurring reminder task to update the webhook secret on the approved cadence.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        problem_id=None,
    )

    ranked = candidate_tickets_for_ticket(base, [different_family, same_family], limit=2)

    assert [ticket.id for ticket in ranked] == ["TW-SR-ACCOUNT", "TW-SR-WEBHOOK"]


# ---------------------------------------------------------------------------
# Taxonomy domain contamination — incident topics should not bleed into SR
# ---------------------------------------------------------------------------


def test_incident_topics_are_distinct_from_sr_topics() -> None:
    """Verify that service_request category hints don't overlap with
    infrastructure-only incident signals like 'network failure'."""
    sr_hints = CATEGORY_HINTS.get("service_request", frozenset())
    incident_only = {"network failure", "packet loss", "ddos", "hardware failure"}
    overlap = sr_hints & incident_only
    assert not overlap, (
        f"service_request CATEGORY_HINTS should not contain incident-only terms: {overlap}"
    )


def test_service_request_guidance_keeps_base_trace_when_llm_refinement_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai.action_refiner.ollama_generate",
        lambda *args, **kwargs: json.dumps(
            {
                "recommended_action": "Create the approved service account for the nightly SFTP import and record the accountable owner before activation.",
                "next_best_actions": [
                    "Apply the approved secret rotation policy and capture the credential handoff in the ticket.",
                    "Confirm the scheduler can authenticate with the new account before closing the request.",
                ],
                "validation_steps": [
                    "Validate one approved SFTP import execution with the new account and confirm the requester sign-off.",
                ],
                "reasoning_note": "This refinement keeps the same provisioning workflow while making the steps more specific.",
            }
        ),
    )

    guidance = build_service_request_guidance(
        type(
            "TicketLike",
            (),
            {
                "title": "Provision service account for the SFTP import job",
                "description": "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
            },
        )(),
        lang="en",
        enable_llm_refinement=True,
    )

    assert guidance["action_refinement_source"] == "service_request_llm"
    assert guidance["recommended_action"].startswith("Create the approved service account")
    assert guidance["base_recommended_action"]
    assert guidance["base_next_best_actions"]
    assert guidance["base_validation_steps"]


def test_service_request_guidance_rejects_off_family_llm_refinement(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai.action_refiner.ollama_generate",
        lambda *args, **kwargs: json.dumps(
            {
                "recommended_action": "Restart the failing service and roll back the last deployment to restore the outage.",
                "next_best_actions": [
                    "Review the root cause and compare the application error logs before proceeding.",
                ],
                "validation_steps": [
                    "Confirm the outage is fully resolved for all users.",
                ],
                "reasoning_note": "This is the confirmed fix for the incident.",
            }
        ),
    )

    guidance = build_service_request_guidance(
        type(
            "TicketLike",
            (),
            {
                "title": "Create webhook rotation reminder task",
                "description": "Create a recurring reminder task to update the webhook secret on the approved cadence.",
            },
        )(),
        lang="en",
        enable_llm_refinement=True,
    )

    assert guidance["action_refinement_source"] == "none"
    assert guidance["display_mode"] == "service_request"
    assert "outage" not in str(guidance["recommended_action"]).lower()
