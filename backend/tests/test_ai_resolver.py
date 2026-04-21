from __future__ import annotations

from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, UserRole
from app.schemas.ai import ChatMessage, ChatRequest
from app.services.ai.intents import IntentConfidence
from app.services.ai import orchestrator, resolver


def _resolver_output(
    *,
    display_mode: str = "evidence_action",
    recommended_action: str | None = "Flush the DNS cache and restart the VPN adapter, then reconnect.",
    root_cause: str | None = "DNS state is stale after reconnect.",
    confidence: float = 0.84,
    confidence_band: str = "high",
    retrieval_source: str = "hybrid_jira_local",
    evidence_reference: str = "TW-3001",
    retrieval_confidence: float = 0.91,
) -> resolver.ResolverOutput:
    payload = {
        "recommended_action": recommended_action,
        "reasoning": "Resolver-approved guidance for the chat flow.",
        "root_cause": root_cause,
        "supporting_context": "Validate on one affected user before wider rollout.",
        "why_this_matches": [
            "The current symptom matches a previously resolved incident.",
        ],
        "evidence_sources": [
            {
                "evidence_type": "resolved ticket",
                "reference": evidence_reference,
                "excerpt": "Flush DNS and restart the VPN adapter, then reconnect.",
                "title": "VPN reconnect DNS failure",
                "relevance": 0.88,
                "why_relevant": "Same reconnect symptom and same fix path.",
            }
        ],
        "confidence": confidence,
        "confidence_band": confidence_band,
        "confidence_label": confidence_band,
        "source_label": retrieval_source,
        "recommendation_mode": "resolved_ticket_grounded",
        "mode": display_mode,
        "display_mode": display_mode,
        "next_best_actions": [
            "Validate the outcome on one affected session before wider rollout.",
        ],
        "validation_steps": [
            "Confirm the affected user can reconnect successfully.",
        ],
        "fallback_action": "Capture the reconnect log and DNS cache state.",
        "missing_information": ["No second independent match yet."] if display_mode != "evidence_action" else [],
        "response_text": "Resolver-approved guidance for the chat flow.",
    }
    advice = resolver.build_resolution_advice_model(payload)
    assert advice is not None
    retrieval = {
        "query_context": {
            "query": "VPN reconnect DNS failure",
            "title": "VPN reconnect DNS failure",
            "tokens": ["vpn", "reconnect", "dns", "failure"],
            "title_tokens": ["vpn", "reconnect", "dns", "failure"],
            "focus_terms": ["vpn", "dns", "reconnect"],
            "domains": ["network"],
            "metadata": {"category": "network"},
        },
        "similar_tickets": [
            {
                "id": evidence_reference,
                "title": "VPN reconnect DNS failure",
                "status": "resolved",
                "similarity_score": 0.91,
                "resolution_snippet": "Flush DNS and restart the VPN adapter, then reconnect.",
            }
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [],
        "confidence": retrieval_confidence,
        "source": retrieval_source,
    }
    return resolver.ResolverOutput(
        mode=advice.display_mode,
        retrieval_query="VPN reconnect DNS failure",
        retrieval=retrieval,
        advice=advice,
        recommended_action=advice.recommended_action,
        reasoning=advice.reasoning,
        match_summary=advice.match_summary,
        root_cause=advice.root_cause,
        supporting_context=advice.supporting_context,
        why_this_matches=list(advice.why_this_matches),
        evidence_sources=list(advice.evidence_sources),
        next_best_actions=list(advice.next_best_actions),
        workflow_steps=list(advice.workflow_steps),
        validation_steps=list(advice.validation_steps),
        fallback_action=advice.fallback_action,
        confidence=advice.confidence,
        missing_information=list(advice.missing_information),
    )


def test_resolve_ticket_advice_builds_structured_workflow_and_validation_steps() -> None:
    ticket = SimpleNamespace(
        id="TW-4100",
        title="VPN sessions drop after reconnect",
        description="Users must reconnect several times after DNS refresh.",
        priority=TicketPriority.high,
        status=None,
        category=TicketCategory.network,
        problem_id=None,
    )

    def fake_retrieve(*args, **kwargs):
        return {
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "status": "resolved",
                    "resolution_snippet": "Flush DNS and restart the VPN adapter, then reconnect.",
                    "similarity_score": 0.93,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.91,
            "source": "hybrid_jira_local",
        }

    def fake_advice_builder(retrieval, *, lang="en"):
        return {
            "recommended_action": "Flush the DNS cache and restart the VPN adapter, then reconnect.",
            "reasoning": "A resolved VPN incident matched the same reconnect and DNS failure pattern.",
            "root_cause": "DNS state is stale after reconnect.",
            "supporting_context": "Confirm the VPN reconnect path on one affected user before broad rollout.",
            "why_this_matches": [
                "The ticket shows VPN reconnect and DNS failure symptoms.",
                "Resolved ticket TW-3001 used the same fix pattern.",
            ],
            "evidence_sources": [
                {
                    "evidence_type": "resolved ticket",
                    "reference": "TW-3001",
                    "excerpt": "Flush DNS and restart the VPN adapter, then reconnect.",
                    "title": "VPN reconnect DNS failure",
                    "relevance": 0.88,
                    "why_relevant": "Same reconnect symptom and same fix path.",
                }
            ],
            "confidence": 0.84,
            "confidence_band": "high",
            "confidence_label": "high",
            "source_label": "hybrid_jira_local",
            "recommendation_mode": "resolved_ticket_grounded",
            "mode": "evidence_action",
            "display_mode": "evidence_action",
            "next_best_actions": [
                "Validate the outcome on one affected session before wider rollout.",
                "Document the validated fix in the incident timeline.",
            ],
            "response_text": "Recommended action: Flush the DNS cache and restart the VPN adapter, then reconnect.",
        }

    output = resolver.resolve_ticket_advice(
        db=object(),
        ticket=ticket,
        visible_tickets=[],
        lang="en",
        retrieval_fn=fake_retrieve,
        advice_builder=fake_advice_builder,
    )

    assert output.mode == "evidence_action"
    assert output.recommended_action == "Flush the DNS cache and restart the VPN adapter, then reconnect."
    assert output.workflow_steps[0] == output.recommended_action
    assert output.validation_steps
    assert output.evidence_sources[0].reference == "TW-3001"
    assert output.advice is not None
    assert output.advice.recommendation_mode == "resolved_ticket_grounded"
    assert output.advice.root_cause == "DNS state is stale after reconnect."
    assert output.advice.why_this_matches
    assert output.advice.evidence_sources[0].why_relevant == "Same reconnect symptom and same fix path."


def test_resolve_ticket_advice_filters_attempted_chat_steps_from_next_actions() -> None:
    ticket = SimpleNamespace(
        id="chat-context",
        title="VPN reconnect still fails",
        description="",
        priority=None,
        status=None,
        category=TicketCategory.network,
        problem_id=None,
    )
    conversation_state = [
        {"role": "user", "content": "I already restarted the VPN adapter and checked the service state."},
        {"role": "assistant", "content": "Thanks, let us narrow it down."},
    ]

    def fake_retrieve(*args, **kwargs):
        return {
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.58,
            "source": "fallback_rules",
        }

    def fake_advice_builder(retrieval, *, lang="en"):
        return {
            "recommended_action": "Collect the VPN DNS cache state before another reconnect attempt.",
            "reasoning": "The remaining mismatch is around DNS state rather than service availability.",
            "evidence_sources": [],
            "confidence": 0.55,
            "confidence_band": "medium",
            "source_label": "fallback_rules",
            "recommendation_mode": "fallback_diagnostic",
            "display_mode": "tentative_diagnostic",
            "next_best_actions": [
                "Restart the VPN adapter and capture the reconnect log.",
                "Collect the VPN DNS cache state before another reconnect attempt.",
                "Validate whether DNS records refresh after the reconnect sequence.",
            ],
            "response_text": "Tentative diagnostic: Collect the VPN DNS cache state before another reconnect attempt.",
        }

    output = resolver.resolve_ticket_advice(
        db=object(),
        ticket=ticket,
        user_question="How do I fix the VPN reconnect issue?",
        conversation_state=conversation_state,
        visible_tickets=[],
        lang="en",
        retrieval_fn=fake_retrieve,
        advice_builder=fake_advice_builder,
    )

    assert all("restart the vpn adapter" not in step.lower() for step in output.next_best_actions)
    assert output.validation_steps


def test_build_resolution_advice_model_keeps_probable_root_cause_unconfirmed() -> None:
    advice = resolver.build_resolution_advice_model(
        {
            "recommended_action": "Generate one control export and validate the corrected date columns in the downstream import.",
            "reasoning": "The strongest evidence stays in the payroll export/date-format family.",
            "probable_root_cause": "Payroll export date serialization drift after the formatter update.",
            "root_cause": None,
            "confidence": 0.44,
            "confidence_band": "low",
            "confidence_label": "low",
            "source_label": "local_lexical",
            "recommendation_mode": "fallback_diagnostic",
            "display_mode": "tentative_diagnostic",
            "validation_steps": [
                "Generate one control export and validate the corrected date columns in the downstream import.",
            ],
            "response_text": "Tentative diagnostic: validate the corrected export path before broader rollout.",
        }
    )

    assert advice is not None
    assert advice.probable_root_cause == "Payroll export date serialization drift after the formatter update."
    assert advice.root_cause is None


def test_build_ticket_retrieval_query_uses_ticket_summary_comments_resolution_and_recent_changes() -> None:
    ticket = SimpleNamespace(
        title="PostgreSQL process killed by OOM killer repeatedly",
        description="The PostgreSQL service is restarted after each OOM event.",
        ai_summary="The database is unstable after a recent configuration update.",
        resolution="Increase shared_buffers carefully only after checking current host memory limits.",
        comments=[
            SimpleNamespace(content="Kernel log shows postgres was OOM-killed after the nightly reporting burst."),
            SimpleNamespace(content="Issue started after the firewall and database maintenance update last week."),
        ],
        tags=["postgresql", "oom", "database"],
    )

    query = resolver.build_ticket_retrieval_query(ticket)

    assert "current_summary=The database is unstable after a recent configuration update." in query
    assert "current_comments=Kernel log shows postgres was OOM-killed after the nightly reporting burst." in query
    assert "current_resolution=Increase shared_buffers carefully only after checking current host memory limits." in query
    assert "recent_changes=" in query
    assert "recent configuration update" in query or "maintenance update last week" in query
    assert "tags=postgresql, oom, database" in query


def test_handle_chat_no_strong_match_uses_resolver_first_reply(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"opening":"Good morning","evidence_summary":"Evidence is still limited.","caution_note":""}',
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: {
            "query_context": {
                "query": "CRM sync job stalls after token rotation",
                "title": "CRM sync job stalls after token rotation",
                "tokens": ["crm", "sync", "job", "stalls", "token", "rotation", "worker"],
                "title_tokens": ["crm", "sync", "job", "stalls", "token", "rotation"],
                "focus_terms": ["crm", "sync", "token", "rotation", "worker"],
                "domains": ["infrastructure"],
                "metadata": {"category": "infrastructure"},
            },
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.0,
            "source": "fallback_rules",
        },
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix the CRM sync job after token rotation?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert "Summary:" in response.reply
    assert "Recommended Action:" in response.reply
    assert "Why this matches:" in response.reply
    assert "Validation:" in response.reply
    assert "Confidence:\nLow -" in response.reply
    assert response.suggestions.resolution_advice is not None
    assert response.suggestions.resolution_advice.display_mode == "no_strong_match"
    assert response.resolution_advice is not None
    assert response.grounding is not None
    assert response.grounding.mode == "no_strong_match"
    assert response.retrieval_mode == "fallback_rules"
    assert response.degraded is True


def test_handle_chat_ticket_guidance_resolves_before_formatter(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: events.append("resolver") or {
            "query_context": {
                "query": "VPN reconnect DNS failure",
                "title": "VPN reconnect DNS failure",
                "tokens": ["vpn", "dns", "reconnect"],
                "title_tokens": ["vpn", "dns", "reconnect"],
                "focus_terms": ["vpn", "dns", "reconnect"],
                "domains": ["network"],
                "metadata": {"category": "network"},
            },
            "similar_tickets": [
                {
                    "id": "TW-3001",
                    "title": "VPN reconnect DNS failure",
                    "status": "resolved",
                    "resolution_snippet": "Flush DNS and restart the VPN adapter, then reconnect.",
                    "similarity_score": 0.92,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.91,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: events.append("llm") or '{"opening":"Good morning","evidence_summary":"This mirrors the prior VPN DNS incident.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix the VPN DNS issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert events[:2] == ["resolver", "llm"]
    assert "Summary:" in response.reply
    assert "Recommended Action:" in response.reply
    assert "Why this matches:" in response.reply
    assert "Validation:" in response.reply
    assert "Confidence:\n" in response.reply
    assert response.grounding is not None
    assert response.grounding.mode == "evidence_action"
    assert response.grounding.evidence_sources[0].reference == "TW-3001"
    assert response.resolution_advice is not None
    assert response.resolution_advice.evidence_sources[0].reference == "TW-3001"


def test_handle_chat_explicit_ticket_guidance_id_uses_resolver_instead_of_ticket_listing(monkeypatch) -> None:
    events: list[str] = []
    ticket = SimpleNamespace(
        id="TW-MOCK-027",
        title="Legal archive access returns permission denied",
        description="Archive folders deny access after a permission change.",
        priority=TicketPriority.high,
        status=SimpleNamespace(value="open"),
        category=TicketCategory.security,
        assignee="Youssef Hamdi",
        reporter="Karim Benali",
    )

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "_answer_data_query",
        lambda *args, **kwargs: events.append("data_query") or ("Tickets correspondants :", "show_ticket", None),
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: events.append("resolver") or {
            "query_context": {
                "query": "Legal archive access returns permission denied",
                "title": "Legal archive access returns permission denied",
                "tokens": ["legal", "archive", "access", "permission", "denied", "acl"],
                "title_tokens": ["legal", "archive", "access", "permission", "denied"],
                "focus_terms": ["archive", "access", "permission", "acl"],
                "domains": ["security", "application"],
                "metadata": {"category": "security"},
            },
            "similar_tickets": [
                {
                    "id": "TW-MOCK-027",
                    "title": "Legal archive access returns permission denied",
                    "status": "resolved",
                    "resolution_snippet": "Restore the archive ACL mapping for the approved legal security group.",
                    "similarity_score": 0.94,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.9,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: events.append("llm") or '{"opening":"Good morning","evidence_summary":"The same archive permission pattern was resolved by restoring the ACL mapping.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="What should I do for this ticket? TW-MOCK-027")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert "data_query" not in events
    assert events[:2] == ["resolver", "llm"]
    assert "Summary:" in response.reply
    assert response.action is None
    assert "Recommended Action:" in response.reply
    assert "Why this matches:" in response.reply
    assert response.grounding is not None
    assert response.grounding.entity_id == "TW-MOCK-027"
    assert response.grounding.mode == "evidence_action"
    assert response.resolution_advice is not None
    assert response.resolution_advice.recommended_action.startswith("Restore the archive ACL mapping")


def test_handle_chat_troubleshooting_prompt_with_ticket_id_uses_resolver_instead_of_summary(monkeypatch) -> None:
    events: list[str] = []
    ticket = SimpleNamespace(
        id="TW-MOCK-019",
        title="CRM sync job stalls after token rotation",
        description="The CRM sync worker stops processing after a token rotation event.",
        priority=TicketPriority.high,
        status=SimpleNamespace(value="open"),
        category=TicketCategory.application,
        assignee="Nadia Boucher",
        reporter="Karim Benali",
    )

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [ticket])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "_answer_data_query",
        lambda *args, **kwargs: events.append("data_query") or ("Ticket details", "show_ticket", None),
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: events.append("resolver") or {
            "query_context": {
                "query": "CRM sync job stalls after token rotation",
                "title": "CRM sync job stalls after token rotation",
                "tokens": ["crm", "sync", "token", "rotation", "worker"],
                "title_tokens": ["crm", "sync", "token", "rotation"],
                "focus_terms": ["crm", "sync", "token", "rotation"],
                "domains": ["application", "integration"],
                "metadata": {"category": "application"},
            },
            "similar_tickets": [
                {
                    "id": "TW-MOCK-041",
                    "title": "CRM worker stalled after expired token cache",
                    "status": "resolved",
                    "resolution_snippet": "Reload the worker token cache and restart the CRM sync worker.",
                    "similarity_score": 0.88,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.77,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: events.append("llm") or '{"summary":["Likely CRM worker token-cache issue after rotation."],"why_this_matches":["A resolved CRM worker incident showed the same token rotation stall pattern."],"confidence_note":"Medium - grounded in a similar resolved incident."}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="Help me troubleshoot TW-MOCK-019")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert "data_query" not in events
    assert events[:2] == ["resolver", "llm"]
    assert "Summary:" in response.reply
    assert "Recommended Action:" in response.reply
    assert response.grounding is not None
    assert response.grounding.entity_id == "TW-MOCK-019"
    assert response.resolution_advice is not None


def test_handle_chat_unseen_guidance_phrase_uses_hybrid_fallback_then_resolver(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "detect_intent_hybrid_details",
        lambda text: (orchestrator.ChatIntent.general, IntentConfidence.low, "llm_fallback", True, False),
    )
    monkeypatch.setattr(
        orchestrator,
        "unified_retrieve",
        lambda *args, **kwargs: events.append("resolver") or {
            "query_context": {
                "query": "Can you walk me through fixing this issue?",
                "title": "Can you walk me through fixing this issue?",
                "tokens": ["fixing", "issue"],
                "title_tokens": ["fixing", "issue"],
                "focus_terms": ["fixing", "issue"],
                "domains": ["application"],
                "metadata": {"category": "application"},
            },
            "similar_tickets": [
                {
                    "id": "TW-MOCK-041",
                    "title": "CRM worker stalled after expired token cache",
                    "status": "resolved",
                    "resolution_snippet": "Reload the worker token cache and restart the CRM sync worker.",
                    "similarity_score": 0.88,
                }
            ],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.77,
            "source": "hybrid_jira_local",
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: events.append("llm") or '{"summary":["Likely worker-token issue."],"why_this_matches":["A resolved worker-token incident matches the same stall pattern."],"confidence_note":"Medium - grounded in one resolved match."}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="Can you walk me through fixing this issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert events[:2] == ["resolver", "llm"]
    assert response.reply.startswith("Summary:")
    assert response.grounding is not None
    assert response.resolution_advice is not None


def test_handle_chat_problem_guidance_uses_problem_resolver_first(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [SimpleNamespace(problem_id="PB-0001")])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "get_problem",
        lambda db, problem_id: SimpleNamespace(
            id=problem_id,
            title="Recurring VPN auth failure",
            root_cause="Stale IdP token cache",
            workaround="Clear the auth cache before reconnect.",
            permanent_fix=None,
            category=TicketCategory.network,
            status=SimpleNamespace(value="investigating"),
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_problem_advice",
        lambda *args, **kwargs: _resolver_output(
            display_mode="evidence_action",
            recommended_action="Clear the auth cache and restart the VPN session.",
            root_cause="Stale IdP token cache",
            evidence_reference="PB-0001",
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"opening":"Good morning","evidence_summary":"The linked problem record confirms the same cache pattern.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix PB-0001?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=object(), current_user=current_user)

    assert response.grounding is not None
    assert response.grounding.entity_type == "problem"
    assert response.grounding.entity_id == "PB-0001"
    assert response.grounding.mode == "evidence_action"
    assert response.reply.startswith("Summary:")
    assert "Recommended Action:" in response.reply
    assert response.suggestions.resolution_advice is not None
    assert response.resolution_advice is not None
    assert response.suggestions.resolution_advice.evidence_sources[0].reference == "PB-0001"
    assert response.resolution_advice.evidence_sources[0].reference == "PB-0001"


def test_handle_chat_tentative_guidance_stays_tentative_after_formatting(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: orchestrator.ChatGuidanceContext(
            grounding=orchestrator._build_chat_grounding(
                entity_type="ticket",
                entity_id=None,
                resolver_output=_resolver_output(
                    display_mode="tentative_diagnostic",
                    confidence=0.58,
                    confidence_band="medium",
                    retrieval_source="local_lexical",
                    retrieval_confidence=0.55,
                ),
            ),
            resolver_output=_resolver_output(
                display_mode="tentative_diagnostic",
                confidence=0.58,
                confidence_band="medium",
                retrieval_source="local_lexical",
                retrieval_confidence=0.55,
            ),
            authoritative=True,
            entity_type="ticket",
            entity_id=None,
            retrieval_mode="lexical_only",
            degraded=True,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"opening":"This is definitely the fix.","evidence_summary":"Apply it everywhere immediately.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix the VPN DNS issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Summary:")
    assert response.resolution_advice is not None
    assert response.resolution_advice.display_mode == "tentative_diagnostic"
    assert response.grounding is not None
    assert response.grounding.mode == "tentative_diagnostic"
    assert "This is a tentative diagnostic, not a confirmed fix." in response.reply
    assert "This is definitely the fix." not in response.reply
    assert "Confidence:\nMedium -" in response.reply


def test_handle_chat_no_strong_match_is_not_upgraded_by_formatter(monkeypatch) -> None:
    resolver_output = _resolver_output(
        display_mode="no_strong_match",
        recommended_action=None,
        root_cause=None,
        confidence=0.18,
        confidence_band="low",
        retrieval_source="fallback_rules",
        retrieval_confidence=0.15,
    )
    resolver_output.advice.fallback_action = "Inspect the worker auth logs and confirm token propagation."
    resolver_output.advice.missing_information = ["No resolved incident matched this token-rotation failure yet."]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: orchestrator.ChatGuidanceContext(
            grounding=orchestrator._build_chat_grounding(
                entity_type="ticket",
                entity_id=None,
                resolver_output=resolver_output,
            ),
            resolver_output=resolver_output,
            authoritative=True,
            entity_type="ticket",
            entity_id=None,
            retrieval_mode="fallback_rules",
            degraded=True,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"opening":"This is the exact fix.","evidence_summary":"Apply it immediately everywhere.","caution_note":""}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="How do I fix the CRM token rotation issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Summary:")
    assert "This is the exact fix." not in response.reply
    assert "Confidence:\nLow -" in response.reply
    assert response.grounding is not None
    assert response.grounding.mode == "no_strong_match"
    assert response.resolution_advice is not None
    assert response.resolution_advice.display_mode == "no_strong_match"


def test_handle_chat_grounded_formatter_deduplicates_repeated_steps(monkeypatch) -> None:
    repeated_step = "Verify the export format against a known valid export before another import."
    resolver_output = _resolver_output(
        display_mode="tentative_diagnostic",
        recommended_action=repeated_step,
        root_cause="Export format mismatch after credential rotation.",
        confidence=0.51,
        confidence_band="medium",
        retrieval_source="local_lexical",
        retrieval_confidence=0.49,
    )
    resolver_output.advice.validation_steps = [repeated_step]
    resolver_output.advice.next_best_actions = [repeated_step, "Restart the integration worker if the export format is correct."]
    resolver_output.advice.why_this_matches = [
        "The ticket shows export-format drift after rotation.",
        "TW-MOCK-036 shows the same export-format mismatch pattern.",
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: orchestrator.ChatGuidanceContext(
            grounding=orchestrator._build_chat_grounding(
                entity_type="ticket",
                entity_id=None,
                resolver_output=resolver_output,
            ),
            resolver_output=resolver_output,
            authoritative=True,
            entity_type="ticket",
            entity_id=None,
            retrieval_mode="lexical_only",
            degraded=True,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "ollama_generate",
        lambda *args, **kwargs: '{"summary":["Likely export format mismatch after rotation."],"why_this_matches":["TW-MOCK-036 shows the same export-format mismatch pattern."],"confidence_note":"Medium - partial match with limited retrieval quality."}',
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="What should I do about this export issue?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Summary:")
    assert response.reply.count(repeated_step) == 1
    assert "Next Steps:" in response.reply
    assert "Restart the integration worker if the export format is correct." in response.reply


def test_handle_chat_generic_non_guidance_can_still_use_llm_first(monkeypatch) -> None:
    llm_calls: list[bool] = []

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: [])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "detect_intent_hybrid_details",
        lambda text: (orchestrator.ChatIntent.general, IntentConfidence.low, "rules_default", False, False),
    )
    monkeypatch.setattr(
        orchestrator,
        "build_chat_reply",
        lambda *args, **kwargs: llm_calls.append(bool(kwargs.get("grounding"))) or ("Generic LLM answer", None, None),
    )
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: orchestrator.ChatGuidanceContext(
            grounding=None,
            resolver_output=None,
            authoritative=False,
        ),
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="Hello, can you summarize what this platform does?")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")

    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Generic LLM answer")
    assert llm_calls == [False]
