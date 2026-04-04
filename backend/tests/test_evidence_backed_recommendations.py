from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import RecommendationType, TicketCategory, TicketPriority, TicketStatus, TicketType
from app.schemas.ai import ClassificationRequest
from app.services.ai import orchestrator
from app.services import recommendations as recommendations_service


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def test_handle_classify_prefers_resolution_advice(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("low-trust LLM branch must not run for grounded evidence_action")),
    )
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.critical,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Collect reconnect timestamps from affected users."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
            "classification_confidence": 79,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "status": "resolved",
                    "resolution_snippet": "Flush the DNS cache and restart the VPN adapter, then reconnect.",
                    "similarity_score": 0.91,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.91,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "NetOps")

    response = orchestrator.handle_classify(
        ClassificationRequest(title="VPN disconnect", description="Users reconnect after DNS failures.", locale="en"),
        db=object(),
    )

    assert response.priority == TicketPriority.critical
    assert response.assignee == "NetOps"
    assert response.recommended_action == "Flush the DNS cache and restart the VPN adapter, then reconnect."
    assert response.recommendations[0] == response.recommended_action
    assert response.recommendation_mode == "resolved_ticket_grounded"
    assert response.display_mode == "evidence_action"
    assert response.source_label == "hybrid_jira_local"
    assert response.resolution_advice is not None
    assert response.resolution_advice.evidence_sources[0].reference == "TW-3001"
    assert response.resolution_advice.mode == "evidence_action"
    assert response.action_refinement_source == "none"
    assert response.mode == "evidence_action"
    assert response.why_this_matches
    assert response.confidence_band in {"medium", "high"}
    assert response.next_best_actions


def test_handle_classify_returns_no_strong_match_when_retrieval_is_empty(monkeypatch) -> None:
    fallback_action = "Collect the VPN adapter state and reconnect logs from affected sessions."
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": [fallback_action],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 68,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "title": "VPN reconnect",
                "description": "Sessions drop every 10 minutes.",
                "metadata": {"category": "network", "priority": "high"},
            },
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.0,
            "source": "fallback_rules",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "NetOps")

    response = orchestrator.handle_classify(
        ClassificationRequest(title="VPN reconnect", description="Sessions drop every 10 minutes.", locale="en"),
        db=object(),
    )

    assert response.recommendation_mode in {"fallback_diagnostic", "insufficient_evidence"}
    assert response.display_mode == "no_strong_match"
    assert response.resolution_advice is not None
    assert response.recommended_action is None
    assert response.recommendations == []
    assert response.source_label == "fallback_rules"
    assert response.guidance_contract is not None
    assert response.guidance_contract.display_mode.value == "manual_triage"


def test_handle_classify_uses_visible_ticket_scope_and_current_ticket_context(monkeypatch) -> None:
    current_ticket = SimpleNamespace(
        id="TW-MOCK-901",
        title="API pods entering CrashLoopBackOff after node pool upgrade",
        description="Existing pods restart after the rollout.",
        status=TicketStatus.open,
        priority=TicketPriority.critical,
        ticket_type=TicketType.incident,
        category=TicketCategory.infrastructure,
        problem_id=None,
        ai_summary="Pods started crashlooping after the node pool upgrade completed.",
        resolution="Patch the deployment manifests to set explicit resource limits before broad rollout.",
        comments=[
            SimpleNamespace(
                author="Leila Ben Amor",
                content="kubectl describe pod confirms OOMKilled on all replicas. Memory request is 512Mi but the new node type enforces 256Mi by default.",
            ),
            SimpleNamespace(
                author="Youssef Hamdi",
                content="Patching the deployment manifests to set explicit resource limits before continuing the rollout on staging first.",
            ),
        ],
    )
    visible_peer = SimpleNamespace(
        id="TW-MOCK-902",
        title="Kubernetes rollout fails after config drift",
        description="A neighbouring platform ticket in the same visible scope.",
        status=TicketStatus.open,
        priority=TicketPriority.high,
        ticket_type=TicketType.incident,
        category=TicketCategory.infrastructure,
        problem_id=None,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.critical,
            "ticket_type": TicketType.incident,
            "classifier_ticket_type": TicketType.incident,
            "category": TicketCategory.infrastructure,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 71,
        },
    )
    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [current_ticket, visible_peer])
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Platform Team")
    monkeypatch.setattr(
        "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
        lambda *args, **kwargs: None,
    )

    def fake_retrieve(db, *, query, visible_tickets, **kwargs):
        captured["query"] = query
        captured["visible_ids"] = [getattr(item, "id", None) for item in list(visible_tickets or [])]
        return {
            "query_context": {
                "title": current_ticket.title,
                "description": current_ticket.description,
                "metadata": {"category": "infrastructure", "priority": "critical"},
            },
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.0,
            "source": "fallback_rules",
        }

    monkeypatch.setattr(orchestrator, "unified_retrieve", fake_retrieve)

    response = orchestrator.handle_classify(
        ClassificationRequest(
            ticket_id=current_ticket.id,
            title=current_ticket.title,
            description=current_ticket.description,
            locale="en",
        ),
        db=object(),
        current_user=SimpleNamespace(id="agent-42"),
    )

    assert response.display_mode == "no_strong_match"
    assert captured["visible_ids"] == [visible_peer.id]
    assert "current_summary=" in str(captured["query"])
    assert "current_comments=" in str(captured["query"])
    assert "OOMKilled" in str(captured["query"])
    assert "current_resolution=" in str(captured["query"])


def test_handle_classify_short_circuits_unresolved_routing_to_manual_triage(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.incident,
            "classifier_ticket_type": TicketType.incident,
            "category": TicketCategory.application,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 62,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "validate_ticket_routing",
        lambda **kwargs: SimpleNamespace(
            use_service_request_guidance=False,
            resolved_ticket_type=TicketType.incident,
            routing_decision_source="cross_check_unresolved",
            cross_check_conflict_flag=True,
            cross_check_summary="Classifier and profile disagree.",
            classifier_ticket_type=TicketType.incident,
            service_request_profile_detected=True,
            service_request_profile_confidence=0.67,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unresolved routing should not enter the incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Amina Rafi")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Update workspace permissions for onboarding",
            description="Update the onboarding workspace permissions and confirm the approved member list.",
            locale="en",
        ),
        db=object(),
    )

    assert response.manual_triage_required is True
    assert response.guidance_contract is not None
    assert response.guidance_contract.display_mode.value == "manual_triage"
    assert response.display_mode == "no_strong_match"
    assert response.recommended_action is None


def test_handle_classify_uses_low_trust_llm_actions_only_for_no_strong_match(monkeypatch) -> None:
    from app.services.ai.action_refiner import LLMActionPackage
    from app.services.ai.resolution_advisor import LLMGeneralAdvisory

    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "classifier_ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 68,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "title": "VPN reconnect",
                "description": "Sessions drop every 10 minutes.",
                "metadata": {"category": "network", "priority": "high"},
            },
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.0,
            "source": "fallback_rules",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "NetOps")
    monkeypatch.setattr("app.services.ai.resolution_advisor._has_specific_guidance_context", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "app.services.ai.resolution_advisor.generate_low_trust_incident_actions",
        lambda *args, **kwargs: LLMActionPackage(
            recommended_action="Validate one affected VPN MFA flow before changing the shared access policy.",
            next_best_actions=[
                "Compare one affected session route and policy snapshot against a healthy finance user.",
                "Document any split-tunnel or session-timeout drift before broad remediation.",
            ],
            validation_steps=["Confirm the MFA loop stops for one affected user after the targeted check."],
            reasoning_note="This remains low-trust guidance based on general IT knowledge only.",
        ),
    )
    monkeypatch.setattr(
        "app.services.ai.resolution_advisor.build_llm_general_advisory",
        lambda *args, **kwargs: LLMGeneralAdvisory(
            probable_causes=["VPN policy drift may trigger repeated MFA prompts."],
            suggested_checks=["Compare one affected route and policy against a healthy finance user."],
            escalation_hint=None,
            knowledge_source="llm_general_knowledge",
            confidence=0.25,
            language="en",
        ),
    )

    response = orchestrator.handle_classify(
        ClassificationRequest(title="VPN reconnect", description="Sessions drop every 10 minutes.", locale="en"),
        db=object(),
    )

    assert response.display_mode == "llm_general_knowledge"
    assert response.recommended_action is not None
    assert response.validation_steps
    assert response.action_refinement_source == "llm_general_knowledge"
    assert response.resolution_advice is not None
    assert response.resolution_advice.llm_general_advisory is not None


def test_handle_classify_bypasses_incident_resolver_for_service_requests(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.service_request,
            "category": TicketCategory.service_request,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 82,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("service requests should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Integrations Team")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Create webhook rotation reminder task",
            description="Create a recurring reminder task to update the webhook secret on the approved cadence.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "service_request"
    assert response.mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.source_label == "service_request"
    assert response.recommended_action is not None
    assert response.root_cause is None
    assert response.probable_root_cause is None
    assert response.next_best_actions
    assert response.guidance_contract is not None
    assert response.guidance_contract.display_mode.value == "service_request"


def test_handle_classify_uses_service_request_guidance_for_planned_dashboard_workflow(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": None,
            "unknown_ticket_type": None,
            "category": TicketCategory.application,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 54,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("planned workflows should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Finance Team")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Build a SLA dashboard for the weekly review",
            description="Build a dashboard for the weekly SLA review with widgets for due tickets, breached SLA, and ticket aging.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.recommended_action is not None
    assert "dashboard" in response.recommended_action.lower()


def test_handle_classify_uses_service_request_guidance_for_device_provisioning_workflow(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": None,
            "unknown_ticket_type": None,
            "category": TicketCategory.hardware,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 57,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("device provisioning should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Support Desk")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Provision a mobile hotspot for a field engineer",
            description="Prepare a mobile hotspot for the field engineer and activate the approved roaming profile before the site visit.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.recommended_action is not None
    assert "device" in response.recommended_action.lower() or "hotspot" in response.recommended_action.lower()


def test_handle_classify_uses_service_request_guidance_for_workspace_membership_request(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.service_request,
            "unknown_ticket_type": None,
            "category": TicketCategory.service_request,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 61,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("workspace membership request should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Procurement Ops")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Add approved members to the procurement workspace",
            description="Add the approved members to the procurement workspace and confirm inherited document access.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.recommended_action is not None


def test_handle_classify_overrides_contextual_incident_label_for_distribution_request(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.incident,
            "unknown_ticket_type": None,
            "category": TicketCategory.email,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 59,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("strong fulfillment profile should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Messaging Ops")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Create distribution list for the ops war room",
            description="Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.recommended_action is not None
    assert "distribution" in response.recommended_action.lower()
    assert response.classifier_ticket_type == TicketType.incident
    assert response.routing_decision_source == "cross_check_profile_override"
    assert response.cross_check_conflict_flag is True
    assert response.service_request_profile_detected is True
    assert response.service_request_profile_confidence > 0.0


def test_handle_classify_falls_back_to_stored_ticket_type_for_service_request_routing(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": None,
            "unknown_ticket_type": None,
            "category": TicketCategory.application,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 52,
        },
    )
    stored_ticket = SimpleNamespace(
        id="TW-MOCK-008",
        title="Install design software on a marketing laptop",
        description="Install the approved design software on the assigned marketing laptop and confirm completion with the requester.",
        ticket_type=TicketType.service_request,
        category=TicketCategory.application,
    )
    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [stored_ticket])
    monkeypatch.setattr(
        orchestrator,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stored service-request type should bypass incident resolver")),
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Marketing IT")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            ticket_id="TW-MOCK-008",
            title=stored_ticket.title,
            description=stored_ticket.description,
            locale="en",
        ),
        db=object(),
        current_user=SimpleNamespace(id="agent-1"),
    )

    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.recommended_action is not None


def test_list_recommendations_uses_resolution_advice_for_ticket_cards(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-900",
        title="VPN DNS outage",
        description="Users lose access until DNS is refreshed.",
        priority=TicketPriority.critical,
        status=TicketStatus.open,
        category=TicketCategory.network,
        problem_id=None,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(recommendations_service, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(
        recommendations_service,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.critical,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Collect VPN logs."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "status": "resolved",
                    "resolution_snippet": "Flush the DNS cache and restart the VPN adapter, then reconnect.",
                    "similarity_score": 0.93,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.93,
            "source": "jira_semantic",
        },
    )

    rows = recommendations_service.list_recommendations(db=object(), user=SimpleNamespace(), locale="en")
    pattern_row = next(row for row in rows if row.type == RecommendationType.pattern)
    solution_row = next(row for row in rows if row.type == RecommendationType.solution)
    workflow_row = next(row for row in rows if row.type == RecommendationType.workflow)

    assert solution_row.entity_type == "ticket"
    assert solution_row.recommended_action.startswith("Flush the DNS cache")
    assert solution_row.recommendation_mode == "resolved_ticket_grounded"
    assert solution_row.display_mode == "evidence_action"
    assert solution_row.source_label == "jira_semantic"
    assert solution_row.evidence_sources[0]["reference"] == "TW-3001"
    assert solution_row.confidence_band in {"medium", "high"}
    assert solution_row.next_best_actions
    assert pattern_row.recommended_action != solution_row.recommended_action
    assert "TW-3001" in pattern_row.recommended_action
    assert workflow_row.recommended_action != solution_row.recommended_action
    assert workflow_row.recommended_action.startswith("Execute the validated action")


def test_list_recommendations_uses_service_request_guidance_for_planned_tasks(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-SR-1",
        title="Create webhook rotation reminder task",
        description="Create a recurring reminder task to update the webhook secret on the approved cadence.",
        priority=TicketPriority.medium,
        status=TicketStatus.open,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        problem_id=None,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(recommendations_service, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(
        recommendations_service,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.service_request,
            "category": TicketCategory.service_request,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("service requests should bypass incident resolver")),
    )
    monkeypatch.setattr(recommendations_service, "get_feedback_bundles_for_recommendations", lambda *args, **kwargs: {})

    rows = recommendations_service.list_recommendations(db=object(), user=SimpleNamespace(id="agent-1"), locale="en")
    solution_row = next(row for row in rows if row.type == RecommendationType.solution)

    assert solution_row.display_mode == "service_request"
    assert solution_row.recommendation_mode == "service_request"
    assert solution_row.source_label == "service_request"
    assert solution_row.probable_root_cause is None
    assert solution_row.recommended_action is not None


def test_list_recommendations_uses_specific_provisioning_runbook_for_account_requests(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-SR-ACCT-1",
        title="Provision service account for the SFTP import job",
        description="Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
        priority=TicketPriority.medium,
        status=TicketStatus.open,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        problem_id=None,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(recommendations_service, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(
        recommendations_service,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.service_request,
            "category": TicketCategory.service_request,
            "recommendations": [],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "resolve_ticket_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("service requests should bypass incident resolver")),
    )
    monkeypatch.setattr(recommendations_service, "get_feedback_bundles_for_recommendations", lambda *args, **kwargs: {})

    rows = recommendations_service.list_recommendations(db=object(), user=SimpleNamespace(id="agent-1"), locale="en")
    solution_row = next(row for row in rows if row.type == RecommendationType.solution)

    assert solution_row.display_mode == "service_request"
    assert solution_row.recommendation_mode == "service_request"
    assert "account" in solution_row.recommended_action.lower()
    assert "planned task" not in (solution_row.reasoning or "").lower()


def test_ticket_recommendation_types_expose_distinct_primary_actions(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-901",
        title="VPN reconnect instability",
        description="Users must refresh DNS before reconnect succeeds.",
        priority=TicketPriority.medium,
        status=TicketStatus.open,
        category=TicketCategory.network,
        problem_id=None,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(
        recommendations_service,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Collect VPN logs."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "status": "resolved",
                    "resolution_snippet": "Flush the DNS cache and restart the VPN adapter, then reconnect.",
                    "similarity_score": 0.93,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.93,
            "source": "jira_semantic",
        },
    )

    rows = recommendations_service._build_ticket_ai_recommendations(
        db=object(),
        ticket=ticket,
        visible_tickets=[ticket],
        lang="en",
    )
    row_by_type = {row.type: row for row in rows}

    assert row_by_type[RecommendationType.solution].recommended_action.startswith("Flush the DNS cache")
    assert row_by_type[RecommendationType.pattern].recommended_action.startswith("Confirm that TW-901 matches the incident pattern")
    assert row_by_type[RecommendationType.priority].recommended_action.startswith("Raise the priority for TW-901 from medium to high")
    assert row_by_type[RecommendationType.workflow].recommended_action.startswith("Execute the validated action for TW-901")


def test_problem_recommendations_prioritize_permanent_fix(monkeypatch) -> None:
    linked_ticket = SimpleNamespace(
        id="TW-321",
        title="Archive access denied",
        description="Legal cannot open archive folders.",
        priority=TicketPriority.critical,
        status=TicketStatus.resolved,
        category=TicketCategory.security,
        problem_id="PB-120",
        resolution="Reapply the ACL mapping.",
        updated_at=_now(),
        created_at=_now(),
    )
    problem = SimpleNamespace(
        id="PB-120",
        title="Archive ACL drift",
        description="Recurring access drift on archive permissions.",
        permanent_fix="Restore archive ACL mapping.",
        workaround="Grant temporary direct access.",
        root_cause="ACL mapping drift for the legal security group.",
        active_count=2,
        occurrences_count=4,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(
        recommendations_service,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-321",
                    "status": "resolved",
                    "resolution_snippet": "Reapply the ACL mapping.",
                    "similarity_score": 0.88,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.88,
            "source": "hybrid_jira_local",
        },
    )

    rows = recommendations_service._build_problem_ai_recommendations(
        db=object(),
        problem=problem,
        linked_tickets=[linked_ticket],
        lang="en",
    )
    solution_row = next(row for row in rows if row.type == RecommendationType.solution)

    assert solution_row.entity_type == "problem"
    assert solution_row.recommended_action == "Restore archive ACL mapping."
    assert solution_row.source_label == "problem_record"
    assert solution_row.evidence_sources[0]["reference"] == "PB-120"


def test_handle_classify_returns_ticket_specific_tentative_step_for_irrelevant_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.application,
            "recommendations": ["Inspect the CSV formatter and compare the date serialization change."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 63,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "query": "Payroll export CSV writes broken date values",
                "title": "Payroll export CSV writes broken date values",
                "tokens": ["payroll", "export", "csv", "date", "values", "imported", "finance", "workbook"],
                "title_tokens": ["payroll", "export", "csv", "date", "values"],
                "focus_terms": ["payroll", "export", "csv", "date", "workbook"],
                "domains": ["application"],
                "metadata": {"category": "application"},
            },
            "similar_tickets": [
                {
                    "id": "TW-5001",
                    "status": "resolved",
                    "resolution_snippet": "Replace the keyboard and dock, then validate desk connectivity.",
                    "similarity_score": 0.95,
                    "context_score": 0.01,
                    "domain_mismatch": True,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.95,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Finance Apps")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Payroll export CSV writes broken date values",
            description="The payroll export CSV is generated, but date columns contain malformed values.",
            locale="en",
        ),
        db=object(),
    )

    assert response.recommended_action is None
    assert response.display_mode == "no_strong_match"
    assert response.recommendation_mode == "fallback_diagnostic"
    assert response.confidence_band == "low"
    assert response.match_summary == "Matched on payroll, export, csv, date."


def test_handle_classify_uses_distribution_change_runbook_for_notification_rule_request(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.medium,
            "ticket_type": TicketType.service_request,
            "category": TicketCategory.email,
            "recommendations": ["Review the approval list."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 61,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "query": "Add payroll distribution rule for approval notices",
                "title": "Add payroll distribution rule for approval notices",
                "description": "Managers should receive payroll approval notices through the expected email distribution rule.",
                "tokens": ["add", "payroll", "distribution", "rule", "approval", "notices", "managers", "email"],
                "title_tokens": ["payroll", "distribution", "rule", "approval", "notices"],
                "focus_terms": ["payroll", "distribution", "approval", "managers", "email"],
                "domains": ["email", "application"],
                "metadata": {"category": "email"},
            },
            "similar_tickets": [
                {
                    "id": "TW-6010",
                    "status": "resolved",
                    "resolution_snippet": "Scheduled the webhook reminder task and confirmed the team subscription.",
                    "similarity_score": 0.64,
                    "context_score": 0.24,
                    "lexical_overlap": 0.04,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.64,
            "source": "jira_semantic",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Messaging Ops")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Add payroll distribution rule for approval notices",
            description="Managers should receive payroll approval notices through the expected email distribution rule.",
            locale="en",
        ),
        db=object(),
    )

    assert response.recommended_action is not None
    assert response.display_mode == "service_request"
    assert response.recommendation_mode == "service_request"
    assert response.resolution_advice is not None
    assert response.resolution_advice.probable_root_cause is None
    assert "distribution" in response.recommended_action.lower()
    assert response.action_relevance_score > 0.0


def test_handle_classify_returns_action_oriented_resolution_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.email,
            "recommendations": ["Review the forwarding configuration."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
            "classification_confidence": 74,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "query": "Teams forwarding stopped after connector rotation",
                "title": "Teams forwarding stopped after connector rotation",
                "tokens": ["teams", "forwarding", "stopped", "connector", "rotation"],
                "title_tokens": ["teams", "forwarding", "connector", "rotation"],
                "focus_terms": ["forwarding", "connector", "rotation"],
                "domains": ["email"],
                "metadata": {"category": "email"},
            },
            "similar_tickets": [
                {
                    "id": "TW-MOCK-009",
                    "status": "resolved",
                    "resolution_snippet": "Resolved by rebuilt the forwarding rule with the current connector identity after connector rotation.",
                    "similarity_score": 0.86,
                    "context_score": 0.56,
                    "lexical_overlap": 0.41,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.86,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Messaging Ops")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="Teams forwarding stopped after connector rotation",
            description="Forwarded messages stopped after the connector identity rotated.",
            locale="en",
        ),
        db=object(),
    )

    assert response.recommended_action == "Rebuild the forwarding rule with the current connector identity after connector rotation."
    assert response.reasoning is not None
    assert 0.0 < response.resolution_confidence < 1.0
    assert response.display_mode == "evidence_action"
    assert response.filtered_weak_match is False
    assert response.resolution_advice is not None
    assert response.resolution_advice.response_text.startswith("Recommended action:")
    assert "Confidence:" in response.resolution_advice.response_text
    assert response.resolution_advice.evidence_sources[0].reference == "TW-MOCK-009"
    assert response.match_summary is not None
    assert response.next_best_actions


def test_handle_classify_filters_cross_domain_mail_recommendation_for_crm_ticket(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.infrastructure,
            "recommendations": ["Refresh the integration token and inspect the stalled worker logs."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": False,
            "classification_confidence": 72,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "query": "CRM sync job stalls after token rotation",
                "title": "CRM sync job stalls after token rotation",
                "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
                "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "contact", "updates", "worker", "integration"],
                "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
                "focus_terms": ["crm", "sync", "token", "rotation", "worker", "integration"],
                "domains": ["infrastructure", "security"],
                "metadata": {"category": "infrastructure"},
            },
            "similar_tickets": [],
            "kb_articles": [
                {
                    "id": "KB-RELAY-9",
                    "title": "Mail relay delivery deferred after certificate renewal",
                    "excerpt": "Resolved by updating the relay certificate chain and clearing the deferred transport queue.",
                    "similarity_score": 0.79,
                    "context_score": 0.27,
                    "lexical_overlap": 0.12,
                    "title_overlap": 0.11,
                    "domain_mismatch": False,
                }
            ],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.79,
            "source": "jira_semantic",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "Integrations Team")

    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="CRM sync job stalls after token rotation",
            description="The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            locale="en",
        ),
        db=object(),
    )

    assert response.display_mode == "no_strong_match"
    assert response.filtered_weak_match is False
    assert response.recommended_action is None
    assert response.confidence_band == "low"


def test_handle_classify_includes_current_feedback_for_ticket_detail(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Restart the VPN gateway service."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
            "classification_confidence": 76,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-1104",
                    "status": "resolved",
                    "resolution_snippet": "Restart the VPN gateway service and refresh the tunnel routes.",
                    "similarity_score": 0.9,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.9,
            "source": "jira_semantic",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: "NetOps")
    monkeypatch.setattr(
        orchestrator,
        "get_feedback_bundle_for_target",
        lambda *args, **kwargs: {
            "current_feedback": {
                "feedback_type": "useful",
                "created_at": _now(),
                "updated_at": _now(),
            },
            "feedback_summary": {
                "total_feedback": 2,
                "useful_count": 1,
                "not_relevant_count": 0,
                "applied_count": 1,
                "rejected_count": 0,
                "usefulness_rate": 0.5,
                "applied_rate": 0.5,
                "rejection_rate": 0.0,
            },
        },
    )

    response = orchestrator.handle_classify(
        ClassificationRequest(
            ticket_id="TW-1105",
            title="VPN sessions fail after route refresh",
            description="Users cannot reconnect until the gateway service is restarted.",
            locale="en",
        ),
        db=object(),
        current_user=SimpleNamespace(id="agent-1"),
    )

    assert response.current_feedback is not None
    assert response.current_feedback.feedback_type == "useful"
    assert response.feedback_summary is not None
    assert response.feedback_summary.total_feedback == 2
    assert response.feedback_summary.applied_count == 1


def test_list_recommendations_attaches_feedback_state(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-920",
        title="VPN adapter loses DNS after reconnect",
        description="Users must restart the adapter after reconnecting.",
        priority=TicketPriority.critical,
        status=TicketStatus.open,
        category=TicketCategory.network,
        problem_id=None,
        updated_at=_now(),
        created_at=_now(),
    )
    monkeypatch.setattr(recommendations_service, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(
        recommendations_service,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.critical,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Restart the VPN adapter service."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "status": "resolved",
                    "resolution_snippet": "Restart the VPN adapter service and refresh DNS.",
                    "similarity_score": 0.93,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.93,
            "source": "jira_semantic",
        },
    )
    monkeypatch.setattr(
        recommendations_service,
        "get_feedback_bundles_for_recommendations",
        lambda *args, **kwargs: {
            recommendation_id: {
                "current_feedback": {
                    "feedback_type": "applied",
                    "created_at": _now(),
                    "updated_at": _now(),
                },
                "feedback_summary": {
                    "total_feedback": 3,
                    "useful_count": 1,
                    "not_relevant_count": 0,
                    "applied_count": 2,
                    "rejected_count": 0,
                    "usefulness_rate": 0.3333,
                    "applied_rate": 0.6667,
                    "rejection_rate": 0.0,
                },
            }
            for recommendation_id in kwargs.get("recommendation_ids", [])
        },
    )

    db = SimpleNamespace(query=lambda *args, **kwargs: None)
    rows = recommendations_service.list_recommendations(db=db, user=SimpleNamespace(id="agent-2"), locale="en")
    solution_row = next(row for row in rows if row.type == RecommendationType.solution)

    assert solution_row.current_feedback is not None
    assert solution_row.current_feedback["feedback_type"] == "applied"
    assert solution_row.feedback_summary is not None
    assert solution_row.feedback_summary["applied_count"] == 2


def test_handle_classify_survives_assignee_lookup_failure(monkeypatch) -> None:
    class _RollbackDB:
        def __init__(self) -> None:
            self.rollbacks = 0

        def rollback(self) -> None:
            self.rollbacks += 1

    monkeypatch.setattr(
        orchestrator,
        "classify_ticket_detailed",
        lambda *args, **kwargs: {
            "priority": TicketPriority.high,
            "ticket_type": TicketType.incident,
            "category": TicketCategory.network,
            "recommendations": ["Restart the VPN gateway service."],
            "recommendations_embedding": [],
            "recommendations_llm": [],
            "recommendation_mode": "fallback_rules",
            "similarity_found": True,
            "classification_confidence": 76,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "similar_tickets": [
                {
                    "id": "TW-1104",
                    "status": "resolved",
                    "resolution_snippet": "Restart the VPN gateway service and refresh the tunnel routes.",
                    "similarity_score": 0.9,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.9,
            "source": "jira_semantic",
        },
    )
    monkeypatch.setattr(orchestrator, "select_best_assignee", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tx_aborted")))

    db = _RollbackDB()
    response = orchestrator.handle_classify(
        ClassificationRequest(
            title="VPN sessions fail after route refresh",
            description="Users cannot reconnect until the gateway service is restarted.",
            locale="en",
        ),
        db=db,
        current_user=SimpleNamespace(id="agent-1"),
    )

    assert response.recommended_action == "Restart the VPN gateway service and refresh the tunnel routes."
    assert response.assignee is None
    assert db.rollbacks == 1
