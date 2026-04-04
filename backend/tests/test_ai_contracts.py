from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.ai import AIResolutionAdvice, GuidanceDisplayMode
from app.services.ai import orchestrator, resolver, retrieval
from app.services.ai.resolver import ResolverOutput


def _ticket(*, ticket_id: str, jira_key: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=ticket_id,
        jira_key=jira_key,
        title=title,
        description=title,
        resolution="Restart worker",
        status=SimpleNamespace(value="resolved"),
        problem_id=None,
        created_at=None,
        updated_at=None,
    )


def test_unified_retrieve_excludes_ids_across_local_and_jira_sources(monkeypatch) -> None:
    self_ticket = _ticket(ticket_id="TW-SELF-1", jira_key="JIRA-SELF-1", title="Current ticket")
    peer_ticket = _ticket(ticket_id="TW-PEER-1", jira_key="JIRA-PEER-1", title="Peer ticket")

    monkeypatch.setattr(retrieval, "kb_has_data", lambda db: True)
    monkeypatch.setattr(retrieval, "compute_embedding", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        retrieval,
        "search_kb_issues",
        lambda db, query, top_k, query_embedding=None: [
            {
                "jira_key": "JIRA-SELF-1",
                "score": 0.98,
                "content": "Self issue content",
                "metadata": {"jira_key": "JIRA-SELF-1", "ticket_id": "TW-SELF-1", "summary": "Current ticket"},
            }
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "search_kb",
        lambda db, query, top_k, source_type=None, query_embedding=None: [
            {"jira_key": "JIRA-SELF-1", "score": 0.97, "content": "Self resolution comment", "source_type": "jira_comment"}
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "_fetch_tickets_for_issue_matches",
        lambda db, issue_matches, ticket_by_jira, ticket_by_id: (
            {**ticket_by_jira, "JIRA-SELF-1": self_ticket, "JIRA-PEER-1": peer_ticket},
            {**ticket_by_id, "TW-SELF-1": self_ticket, "TW-PEER-1": peer_ticket},
        ),
    )
    monkeypatch.setattr(
        retrieval,
        "_local_ticket_matches",
        lambda query, tickets, query_context, limit=8: [
            {"id": "TW-SELF-1", "jira_key": "JIRA-SELF-1", "title": "Current ticket", "status": "resolved", "similarity_score": 0.99, "source": "local_lexical"},
            {"id": "TW-PEER-1", "jira_key": "JIRA-PEER-1", "title": "Peer ticket", "status": "resolved", "similarity_score": 0.78, "source": "local_lexical"},
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "_local_ticket_semantic_matches",
        lambda query, tickets, query_context, lexical_seed, limit=8, query_embedding=None: [],
    )
    monkeypatch.setattr(retrieval, "_search_related_problems", lambda *args, **kwargs: [])
    monkeypatch.setattr(retrieval, "list_comments_for_jira_keys", lambda db, jira_keys, limit_per_issue=2: [])
    monkeypatch.setattr(retrieval, "aggregate_feedback_for_sources", lambda *args, **kwargs: {})

    result = retrieval.unified_retrieve(
        MagicMock(),
        query="Current ticket worker failure",
        visible_tickets=[self_ticket, peer_ticket],
        top_k=3,
        exclude_ids=["TW-SELF-1"],
    )

    assert result.excluded_ids == ["TW-SELF-1"]
    assert [row["id"] for row in result.similar_tickets] == ["TW-PEER-1"]
    assert result.kb_articles == []
    assert result.solution_recommendations == []


def test_guidance_contract_downgrades_low_confidence_payloads() -> None:
    advice = AIResolutionAdvice(
        recommended_action="Restart the sync worker.",
        reasoning="Strong advisor hypothesis based on aligned symptoms.",
        confidence=0.82,
        confidence_band="high",
        confidence_label="high",
        display_mode="evidence_action",
        mode="evidence_action",
        response_text="Restart the sync worker.",
    )
    resolver_output = ResolverOutput(
        mode="evidence_action",
        retrieval_query="worker token rotation",
        retrieval={
            "similar_tickets": [{"id": "TW-100", "title": "Worker token rotation", "status": "resolved", "similarity_score": 0.84}],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.35,
            "source": "hybrid_jira_local",
        },
        advice=advice,
        recommended_action=advice.recommended_action,
        reasoning=advice.reasoning,
        match_summary=None,
        confidence=advice.confidence,
    )

    bundle = orchestrator._build_suggestion_bundle(resolver_output, lang="en")

    assert bundle.guidance_contract is not None
    assert bundle.guidance_contract.display_mode == GuidanceDisplayMode.needs_more_info
    assert bundle.guidance_contract.legacy_display_mode == GuidanceDisplayMode.tentative_diagnostic
    assert bundle.confidence == 0.35
    assert bundle.tickets == []
    assert bundle.resolution_advice is not None
    assert bundle.resolution_advice.display_mode == GuidanceDisplayMode.tentative_diagnostic


def test_resolution_advice_model_keeps_llm_general_advisory_payload() -> None:
    advice = resolver.build_resolution_advice_model(
        {
            "recommended_action": "Validate one affected sync worker before changing the shared token policy.",
            "reasoning": "No local evidence passed the guardrails.",
            "confidence": 0.25,
            "confidence_band": "low",
            "display_mode": "llm_general_knowledge",
            "mode": "llm_general_knowledge",
            "base_recommended_action": "Collect additional token-refresh detail before changing the shared policy.",
            "base_next_best_actions": ["Compare one affected worker with a healthy worker."],
            "base_validation_steps": ["Confirm the worker reloads the refreshed token."],
            "action_refinement_source": "llm_general_knowledge",
            "validation_steps": ["Confirm the targeted check narrowed the issue scope."],
            "next_best_actions": ["Compare the affected worker with one healthy worker before broad remediation."],
            "response_text": "General advisory only.",
            "knowledge_source": "llm_general_knowledge",
            "llm_general_advisory": {
                "probable_causes": ["Token cache not refreshed after rotation."],
                "suggested_checks": ["Verify one affected sync worker reloaded the credential."],
                "escalation_hint": "Escalate to the integrations owner if the cache remains stale.",
                "knowledge_source": "llm_general_knowledge",
                "confidence": 0.25,
                "language": "en",
            },
        },
        default_source_label="fallback_rules",
        lang="en",
    )

    assert advice is not None
    assert advice.display_mode == GuidanceDisplayMode.llm_general_knowledge
    assert advice.knowledge_source == "llm_general_knowledge"
    assert advice.base_recommended_action == "Collect additional token-refresh detail before changing the shared policy."
    assert advice.action_refinement_source == "llm_general_knowledge"
    assert advice.llm_general_advisory is not None
    assert advice.llm_general_advisory.probable_causes == ["Token cache not refreshed after rotation."]

    payload = resolver.resolution_advice_to_payload(advice)
    assert payload is not None
    assert payload["knowledge_source"] == "llm_general_knowledge"
    assert payload["action_refinement_source"] == "llm_general_knowledge"
    assert payload["base_recommended_action"] == "Collect additional token-refresh detail before changing the shared policy."
    assert payload["llm_general_advisory"]["knowledge_source"] == "llm_general_knowledge"


def test_guidance_contract_preserves_service_request_mode() -> None:
    advice = AIResolutionAdvice(
        recommended_action="Confirm the approved cadence before updating the reminder task.",
        reasoning="This ticket matches a planned webhook-rotation workflow.",
        confidence=0.72,
        confidence_band="medium",
        confidence_label="medium",
        display_mode="service_request",
        mode="service_request",
        response_text="Service request guidance.",
    )
    resolver_output = ResolverOutput(
        mode="service_request",
        retrieval_query="webhook rotation reminder",
        retrieval={
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.0,
            "source": "service_request",
        },
        advice=advice,
        recommended_action=advice.recommended_action,
        reasoning=advice.reasoning,
        match_summary=None,
        confidence=advice.confidence,
    )

    retrieval_result, contract = orchestrator._build_guidance_contract(resolver_output)

    assert retrieval_result.source == "service_request"
    assert contract is not None
    assert contract.display_mode == GuidanceDisplayMode.service_request
    assert contract.legacy_display_mode == GuidanceDisplayMode.service_request
    assert contract.downgraded is False
    assert contract.evidence_allowed is False
