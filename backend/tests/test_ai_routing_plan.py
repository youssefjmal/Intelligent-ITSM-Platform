from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ai import AIChatGrounding, AIResolutionAdvice, AIResolutionEvidence, ChatMessage, ChatRequest
from app.services.ai.chat_payloads import build_cause_analysis_payload, build_insufficient_evidence_payload
from app.services.ai import intents, orchestrator
from app.services.ai.intents import ChatIntent, IntentConfidence
from app.services.ai.resolver import ResolverOutput


def _ticket(
    *,
    ticket_id: str,
    title: str,
    description: str,
    status: TicketStatus,
    priority: TicketPriority,
    category: TicketCategory,
    assignee: str,
    reporter: str,
    created_at: dt.datetime,
    sla_status: str | None = None,
    problem_id: str | None = None,
):
    return SimpleNamespace(
        id=ticket_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        category=category,
        assignee=assignee,
        reporter=reporter,
        resolution=None,
        comments=[],
        tags=[],
        created_at=created_at,
        updated_at=created_at,
        jira_created_at=None,
        jira_updated_at=None,
        sla_status=sla_status,
        sla_due_at=None,
        sla_remaining_minutes=None,
        sla_remaining_human=None,
        problem_id=problem_id,
        assignment_change_count=0,
        first_action_at=None,
        resolved_at=None,
    )


def _resolver_output(*, confidence: float = 0.74, root_cause: str | None = "Token refresh was not reloaded by the worker") -> ResolverOutput:
    advice = AIResolutionAdvice(
        recommended_action="Restart the CRM sync worker after refreshing the integration token.",
        reasoning="Recent evidence points to token refresh propagation failing on the worker process.",
        probable_root_cause=root_cause,
        root_cause=root_cause,
        supporting_context="Two similar incidents were resolved by reloading the worker after token rotation.",
        why_this_matches=[
            "The ticket mentions the sync job stalling immediately after token rotation.",
            "Retrieved similar incidents reference worker restart after token update.",
        ],
        evidence_sources=[
            AIResolutionEvidence(
                evidence_type="similar_ticket",
                reference="TW-MOCK-017",
                excerpt="Resolved by restarting the CRM sync worker after rotating the OAuth token.",
            ),
            AIResolutionEvidence(
                evidence_type="comment",
                reference="comment: token rotation observed",
                excerpt="Rotation completed but the worker kept using the previous credential cache.",
            ),
        ],
        tentative=confidence < 0.7,
        confidence=confidence,
        confidence_band="high" if confidence >= 0.78 else "medium" if confidence >= 0.52 else "low",
        confidence_label="high" if confidence >= 0.78 else "medium" if confidence >= 0.52 else "low",
        source_label="hybrid_jira_local",
        recommendation_mode="evidence_first",
        action_relevance_score=confidence,
        filtered_weak_match=False,
        mode="evidence_action",
        display_mode="evidence_action" if confidence >= 0.7 else "tentative_diagnostic",
        match_summary="The strongest retrieved evidence points to stale worker credentials after token rotation.",
        next_best_actions=[
            "Confirm the worker has reloaded the latest integration secret.",
            "Re-run one controlled CRM sync job and monitor completion.",
        ],
        workflow_steps=[
            "Restart the CRM sync worker after applying the fresh token.",
            "Replay one stalled sync batch and confirm records move again.",
        ],
        validation_steps=[
            "Check the worker logs for successful token reload.",
            "Verify the next scheduled sync completes without stalling.",
        ],
        fallback_action="Collect one fresh worker log excerpt before making a broader configuration change.",
        missing_information=[],
        response_text="Restart the CRM sync worker after token rotation, then validate the next sync run.",
    )
    retrieval = {
        "query_context": {"query": "CRM sync job stalls after token rotation"},
        "similar_tickets": [
            {
                "id": "TW-MOCK-017",
                "title": "CRM sync queue stalls after credential refresh",
                "similarity_score": 0.88,
                "status": "resolved",
                "resolution_snippet": "Restart worker after token update.",
                "match_reason": "Matched on CRM sync worker, token rotation, and stalled queue symptoms.",
            },
            {
                "id": "TW-MOCK-021",
                "title": "CRM import worker froze after OAuth secret change",
                "similarity_score": 0.81,
                "status": "resolved",
                "resolution_snippet": "Reload worker credentials and replay queue.",
                "match_reason": "Matched on worker credential cache and post-rotation failure pattern.",
            },
        ],
        "kb_articles": [],
        "solution_recommendations": [],
        "related_problems": [
            {
                "id": "PB-MOCK-02",
                "title": "Recurring CRM sync worker credential reload failures",
                "root_cause": "Worker process did not reload rotated integration credentials",
                "match_reason": "Recurring credential reload problem linked to CRM sync jobs.",
                "similarity_score": 0.79,
            }
        ],
        "grounded_action_steps": [
            {
                "step": 1,
                "text": "Restart the CRM sync worker after refreshing the integration token.",
                "reason": "TW-MOCK-017 and TW-MOCK-021 both point to worker-side token reload failure after rotation.",
                "evidence": ["resolved ticket: TW-MOCK-017", "resolved ticket: TW-MOCK-021", "signal: token rotation"],
            },
            {
                "step": 2,
                "text": "Re-run one controlled CRM sync job and monitor the worker for authentication failures.",
                "reason": "A controlled replay confirms the refreshed credential is actually being used.",
                "evidence": ["comment: token rotation observed", "signal: sync worker"],
            },
        ],
        "confidence": confidence,
        "source": "hybrid_jira_local",
    }
    return ResolverOutput(
        mode="evidence_action",
        retrieval_query="CRM sync job stalls after token rotation",
        retrieval=retrieval,
        advice=advice,
        recommended_action=advice.recommended_action,
        reasoning=advice.reasoning,
        match_summary=advice.match_summary,
        root_cause=root_cause,
        supporting_context=advice.supporting_context,
        why_this_matches=list(advice.why_this_matches),
        evidence_sources=list(advice.evidence_sources),
        next_best_actions=list(advice.next_best_actions),
        workflow_steps=list(advice.workflow_steps),
        validation_steps=list(advice.validation_steps),
        fallback_action=advice.fallback_action,
        confidence=confidence,
        missing_information=list(advice.missing_information),
    )


def _authoritative_ticket_guidance(
    resolver_output: ResolverOutput,
    *,
    ticket_id: str = "TW-MOCK-019",
    confidence_band: str = "medium",
    degraded: bool = False,
) -> orchestrator.ChatGuidanceContext:
    return orchestrator.ChatGuidanceContext(
        grounding=AIChatGrounding(
            entity_type="ticket",
            entity_id=ticket_id,
            mode=resolver_output.mode,
            confidence_band=confidence_band,
            root_cause=resolver_output.root_cause,
            recommended_action=resolver_output.recommended_action,
            supporting_context=resolver_output.supporting_context,
            why_this_matches=list(resolver_output.why_this_matches),
            evidence_sources=list(resolver_output.evidence_sources),
            validation_steps=list(resolver_output.validation_steps),
            fallback_action=resolver_output.fallback_action,
            next_best_actions=list(resolver_output.next_best_actions),
            missing_information=list(resolver_output.missing_information),
            retrieval_mode=str((resolver_output.retrieval or {}).get("source") or "fallback_rules"),
            degraded=degraded,
        ),
        resolver_output=resolver_output,
        authoritative=True,
        entity_type="ticket",
        entity_id=ticket_id,
        retrieval_mode=str((resolver_output.retrieval or {}).get("source") or "fallback_rules"),
        degraded=degraded,
    )


def test_recent_intent_constraint_detection_en_fr() -> None:
    assert intents.detect_intent("latest ticket") == ChatIntent.recent_ticket
    assert intents.has_recent_ticket_constraints("latest ticket") is False

    constrained_en = intents.extract_recent_ticket_constraints("latest ticket vpn")
    assert "vpn" in constrained_en
    assert intents.has_recent_ticket_constraints("latest ticket vpn") is True

    constrained_fr = intents.extract_recent_ticket_constraints("dernier ticket vpn")
    assert "vpn" in constrained_fr
    assert intents.has_recent_ticket_constraints("dernier ticket vpn") is True


def test_build_routing_plan_recent_shortcut_vs_filtered() -> None:
    plain_intent = intents.detect_intent("latest ticket")
    plain_plan = orchestrator.build_routing_plan("latest ticket", intent=plain_intent, create_requested=False)
    assert plain_plan.name == "shortcut_recent_ticket"
    assert plain_plan.use_llm is False

    constrained_intent = intents.detect_intent("latest ticket vpn")
    constrained_plan = orchestrator.build_routing_plan(
        "latest ticket vpn",
        intent=constrained_intent,
        create_requested=False,
    )
    assert constrained_plan.name == "recent_ticket_filtered"
    assert constrained_plan.use_llm is True
    assert "vpn" in constrained_plan.constraints


def test_ticket_guidance_query_with_explicit_id_is_not_treated_as_data_query() -> None:
    query = "What should I do for this ticket? TW-2002"

    assert intents.detect_intent(query) == ChatIntent.general
    assert orchestrator.is_guidance_request(query) is True
    assert orchestrator._detect_unified_pattern(query, plan=orchestrator.RoutingPlan(
        name="general_llm",
        intent=ChatIntent.general,
        use_llm=True,
        use_kb=True,
    )) == "HOW_TO_FIX"


def test_troubleshooting_query_with_explicit_id_prefers_guidance_intent() -> None:
    query = "Help me troubleshoot TW-MOCK-019"

    assert intents.detect_intent(query) == ChatIntent.general
    assert orchestrator.is_guidance_request(query) is True
    assert orchestrator._detect_unified_pattern(query, plan=orchestrator.RoutingPlan(
        name="general_llm",
        intent=ChatIntent.general,
        use_llm=True,
        use_kb=True,
    )) == "HOW_TO_FIX"


def test_explicit_ticket_info_queries_stay_on_summary_path() -> None:
    assert intents.detect_intent("Show me details of TW-MOCK-019") == ChatIntent.data_query
    assert intents.detect_intent("Give me the status of this ticket") == ChatIntent.data_query


def test_resolve_ticket_context_prefers_explicit_then_prior_single_ticket() -> None:
    explicit_ticket_id, explicit_source = orchestrator.resolve_ticket_context(
        "Show me details of TW-MOCK-019",
        [],
    )
    contextual_ticket_id, contextual_source = orchestrator.resolve_ticket_context(
        "What is the status?",
        [
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
        ],
    )

    assert explicit_ticket_id == "TW-MOCK-019"
    assert explicit_source == "explicit"
    assert contextual_ticket_id == "TW-MOCK-019"
    assert contextual_source == "context"


def test_why_is_this_happening_query_is_guidance_intent() -> None:
    query = "Why is this issue happening?"

    assert intents.detect_intent(query) == ChatIntent.general
    assert orchestrator.is_guidance_request(query) is True


def test_detect_intent_with_confidence_known_keyword_stays_rule_based() -> None:
    intent, confidence = intents.detect_intent_with_confidence("what should I do for this ticket?")

    assert intent == ChatIntent.general
    assert confidence == IntentConfidence.high


def test_detect_intent_with_confidence_info_request_is_high_confidence() -> None:
    intent, confidence = intents.detect_intent_with_confidence("show me details of TW-MOCK-019")

    assert intent == ChatIntent.data_query
    assert confidence == IntentConfidence.high


def test_detect_intent_hybrid_uses_llm_fallback_for_unseen_guidance_phrasing(monkeypatch) -> None:
    llm_calls = {"count": 0}

    monkeypatch.setattr(
        intents,
        "_classify_intent_llm_label",
        lambda text: llm_calls.__setitem__("count", llm_calls["count"] + 1) or "guidance",
    )

    intent, confidence, source, guidance = intents.detect_intent_hybrid_details(
        "Can you walk me through fixing this issue?"
    )

    assert intent == ChatIntent.general
    assert confidence == IntentConfidence.medium
    assert source == "llm_fallback"
    assert guidance is True
    assert llm_calls["count"] == 1


def test_detect_intent_hybrid_uses_llm_fallback_for_ambiguous_prompt(monkeypatch) -> None:
    llm_calls = {"count": 0}

    monkeypatch.setattr(
        intents,
        "_classify_intent_llm_label",
        lambda text: llm_calls.__setitem__("count", llm_calls["count"] + 1) or "guidance",
    )

    intent, confidence, source, guidance = intents.detect_intent_hybrid_details("this looks weird")

    assert intent == ChatIntent.general
    assert confidence == IntentConfidence.low
    assert source == "llm_fallback"
    assert guidance is True
    assert llm_calls["count"] == 1


def test_handle_chat_recent_plain_uses_shortcut(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-2001",
            title="Email delivery delayed",
            description="mail issue",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.email,
            assignee="Nora",
            reporter="Sara",
            created_at=now - dt.timedelta(minutes=15),
        ),
        _ticket(
            ticket_id="TW-2002",
            title="VPN disconnects",
            description="vpn unstable",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.network,
            assignee="Maya",
            reporter="Adam",
            created_at=now - dt.timedelta(minutes=5),
        ),
    ]
    llm_calls = {"count": 0}

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Maya")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(orchestrator, "_format_most_recent_ticket", lambda recent, lang, open_only=False: "shortcut_recent")
    monkeypatch.setattr(
        orchestrator,
        "build_chat_reply",
        lambda *args, **kwargs: llm_calls.__setitem__("count", llm_calls["count"] + 1) or ("llm", None, None),
    )

    payload = ChatRequest(messages=[ChatMessage(role="user", content="latest ticket")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply == "shortcut_recent"
    assert llm_calls["count"] == 0


def test_handle_chat_recent_with_constraint_uses_llm(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-3001",
            title="Outlook profile reset needed",
            description="email issue",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.email,
            assignee="Nora",
            reporter="Sara",
            created_at=now - dt.timedelta(minutes=15),
        ),
        _ticket(
            ticket_id="TW-3002",
            title="VPN tunnel drops every hour",
            description="vpn gateway unstable",
            status=TicketStatus.pending,
            priority=TicketPriority.high,
            category=TicketCategory.network,
            assignee="Maya",
            reporter="Adam",
            created_at=now - dt.timedelta(minutes=5),
        ),
    ]
    llm_calls = {"count": 0}
    shortcut_calls = {"count": 0}

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Maya")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "_format_most_recent_ticket",
        lambda recent, lang, open_only=False: shortcut_calls.__setitem__("count", shortcut_calls["count"] + 1) or "shortcut_recent",
    )
    monkeypatch.setattr(
        orchestrator,
        "build_chat_reply",
        lambda *args, **kwargs: llm_calls.__setitem__("count", llm_calls["count"] + 1) or ("llm_path", None, None),
    )
    monkeypatch.setattr(orchestrator, "_answer_data_query", lambda *args, **kwargs: None)

    payload = ChatRequest(messages=[ChatMessage(role="user", content="latest ticket vpn")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply == "llm_path"
    assert llm_calls["count"] == 1
    assert shortcut_calls["count"] == 0


def test_handle_chat_explicit_ticket_details_return_single_ticket(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-027",
            title="Legal archive access returns permission denied",
            description="Archive access fails.",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.security,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(messages=[ChatMessage(role="user", content="Show me details of TW-MOCK-019")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Ticket TW-MOCK-019 details:")
    assert "Tickets correspondants" not in response.reply
    assert response.action == "show_ticket"
    assert response.ticket is not None
    assert response.ticket.title.startswith("TW-MOCK-019")
    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_details"
    assert response.response_payload.ticket_id == "TW-MOCK-019"


def test_handle_chat_status_of_this_ticket_uses_prior_ticket_context(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-027",
            title="Legal archive access returns permission denied",
            description="Archive access fails.",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.security,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Give me the status of this ticket"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Ticket TW-MOCK-019 status:")
    assert "- Ticket ID: TW-MOCK-019" in response.reply
    assert "- Status: In progress" in response.reply
    assert "- Priority: High" in response.reply
    assert "- Assignee: Nadia Boucher" in response.reply
    assert "Tickets correspondants" not in response.reply
    assert response.action is None
    assert response.ticket is None
    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_status"
    assert response.response_payload.ticket_id == "TW-MOCK-019"


def test_handle_chat_status_question_uses_prior_ticket_context(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="What is the status?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Ticket TW-MOCK-019 status:")
    assert "Tickets correspondants" not in response.reply
    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_status"


def test_handle_chat_show_me_second_one_uses_last_ticket_list(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-010",
            title="VPN login loop after MFA change",
            description="Users are repeatedly asked to re-authenticate.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.network,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
            sla_status="at_risk",
        ),
        _ticket(
            ticket_id="TW-MOCK-011",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
            sla_status="at_risk",
        ),
        _ticket(
            ticket_id="TW-MOCK-012",
            title="HR export date formatting defect",
            description="Export still works but date format is wrong.",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=3),
            sla_status="ok",
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me all high SLA tickets"),
            ChatMessage(
                role="assistant",
                content=(
                    "Matching tickets:\n"
                    "- TW-MOCK-010 | VPN login loop after MFA change\n"
                    "- TW-MOCK-011 | CRM sync job stalls after token rotation"
                ),
            ),
            ChatMessage(role="user", content="Show me the second one"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Ticket TW-MOCK-011 details:")
    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_details"
    assert response.response_payload.ticket_id == "TW-MOCK-011"


def test_handle_chat_compare_previous_ticket_uses_last_two_mentions(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-025",
            title="Payroll export writes invalid date columns",
            description="Payroll export produces broken date values.",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-025 details:"),
            ChatMessage(role="user", content="Compare it with the previous one"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Ticket comparison: TW-MOCK-025 vs TW-MOCK-019")
    assert response.ticket_results is not None
    assert response.ticket_results.kind == "comparison"
    assert [row.id for row in response.ticket_results.tickets] == ["TW-MOCK-025", "TW-MOCK-019"]


def test_handle_chat_short_why_followup_reuses_prior_ticket_context(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.78)

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: _authoritative_ticket_guidance(resolver_output, confidence_band="high"),
    )
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Cause analysis", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="What should I do for TW-MOCK-019?"),
            ChatMessage(
                role="assistant",
                content="Recommended action for TW-MOCK-019: Restart the CRM sync worker after refreshing the integration token.",
            ),
            ChatMessage(role="user", content="Why?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "cause_analysis"
    assert response.response_payload.ticket_id == "TW-MOCK-019"


def test_handle_chat_followup_guidance_does_not_drift_to_assistant_suggestion_ticket(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-025",
            title="Payroll export writes invalid date columns",
            description="Payroll export produces broken date values.",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.application,
            assignee="Karim Benali",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-008",
            title="Create finance-alerts distribution list",
            description="Create a mailing list for payroll and audit notifications.",
            status=TicketStatus.open,
            priority=TicketPriority.low,
            category=TicketCategory.service_request,
            assignee="Nadia Boucher",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.64, root_cause="Payroll export date serialization drift")
    captured: dict[str, str | None] = {}

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Karim Benali")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    def _fake_guidance(**kwargs):
        captured["resolved_ticket_id"] = kwargs.get("resolved_ticket_id")
        ticket_id = str(kwargs.get("resolved_ticket_id") or "TW-MOCK-025")
        return _authoritative_ticket_guidance(resolver_output, ticket_id=ticket_id, confidence_band="medium")

    monkeypatch.setattr(orchestrator, "resolve_chat_guidance", _fake_guidance)
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Structured guidance", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(
                role="assistant",
                content=(
                    "Ticket TW-MOCK-025 details.\n"
                    "Related suggestions: TW-MOCK-013, TW-MOCK-032, TW-MOCK-008"
                ),
            ),
            ChatMessage(role="user", content="What should I do next for this ticket?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert captured["resolved_ticket_id"] == "TW-MOCK-025"
    assert response.response_payload is not None
    assert response.response_payload.type == "resolution_advice"
    assert response.response_payload.ticket_id == "TW-MOCK-025"


def test_handle_chat_similar_tickets_followup_uses_sticky_active_ticket(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-025",
            title="Payroll export writes invalid date columns",
            description="Payroll export produces broken date values.",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.application,
            assignee="Karim Benali",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-008",
            title="Create finance-alerts distribution list",
            description="Create a mailing list for payroll and audit notifications.",
            status=TicketStatus.open,
            priority=TicketPriority.low,
            category=TicketCategory.service_request,
            assignee="Nadia Boucher",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.72, root_cause="Payroll export date serialization drift")
    captured: dict[str, str | None] = {}

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Karim Benali")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    def _fake_guidance(**kwargs):
        captured["resolved_ticket_id"] = kwargs.get("resolved_ticket_id")
        ticket_id = str(kwargs.get("resolved_ticket_id") or "TW-MOCK-025")
        return _authoritative_ticket_guidance(resolver_output, ticket_id=ticket_id, confidence_band="medium")

    monkeypatch.setattr(orchestrator, "resolve_chat_guidance", _fake_guidance)
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Similar tickets", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(
                role="assistant",
                content=(
                    "Ticket TW-MOCK-025 details.\n"
                    "Related suggestions: TW-MOCK-013, TW-MOCK-032, TW-MOCK-008"
                ),
            ),
            ChatMessage(role="user", content="Which tickets are similar to this one?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert captured["resolved_ticket_id"] == "TW-MOCK-025"
    assert response.response_payload is not None
    assert response.response_payload.type == "similar_tickets"
    assert response.response_payload.source_ticket_id == "TW-MOCK-025"


def test_handle_chat_why_followup_after_positional_selection_keeps_selected_ticket(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
            sla_status="breached",
        ),
        _ticket(
            ticket_id="TW-MOCK-025",
            title="Payroll export writes invalid date columns",
            description="Payroll export produces broken date values.",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.application,
            assignee="Karim Benali",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=2),
            sla_status="at_risk",
        ),
        _ticket(
            ticket_id="TW-MOCK-008",
            title="Create finance-alerts distribution list",
            description="Create a mailing list for payroll and audit notifications.",
            status=TicketStatus.open,
            priority=TicketPriority.low,
            category=TicketCategory.service_request,
            assignee="Nadia Boucher",
            reporter="Finance Lead",
            created_at=now - dt.timedelta(hours=3),
            sla_status="ok",
        ),
    ]
    resolver_output = _resolver_output(confidence=0.68, root_cause="Payroll export date serialization drift")
    captured: dict[str, str | None] = {}

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Karim Benali")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    def _fake_guidance(**kwargs):
        captured["resolved_ticket_id"] = kwargs.get("resolved_ticket_id")
        ticket_id = str(kwargs.get("resolved_ticket_id") or "TW-MOCK-025")
        return _authoritative_ticket_guidance(resolver_output, ticket_id=ticket_id, confidence_band="medium")

    monkeypatch.setattr(orchestrator, "resolve_chat_guidance", _fake_guidance)
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Cause analysis", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show high SLA tickets"),
            ChatMessage(
                role="assistant",
                content=(
                    "Matching tickets:\n"
                    "- TW-MOCK-019 | CRM sync job stalls after token rotation\n"
                    "- TW-MOCK-025 | Payroll export writes invalid date columns"
                ),
            ),
            ChatMessage(role="user", content="Show me the second one"),
            ChatMessage(
                role="assistant",
                content=(
                    "Ticket TW-MOCK-025 details.\n"
                    "Related suggestions: TW-MOCK-008"
                ),
            ),
            ChatMessage(role="user", content="Why is this happening?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert captured["resolved_ticket_id"] == "TW-MOCK-025"
    assert response.response_payload is not None
    assert response.response_payload.type == "cause_analysis"
    assert response.response_payload.ticket_id == "TW-MOCK-025"


def test_handle_chat_show_all_tickets_keeps_list_behavior(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
        _ticket(
            ticket_id="TW-MOCK-027",
            title="Legal archive access returns permission denied",
            description="Archive access fails.",
            status=TicketStatus.open,
            priority=TicketPriority.high,
            category=TicketCategory.security,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Show me all tickets"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.reply.startswith("Matching tickets:")
    assert "TW-MOCK-019" in response.reply
    assert "TW-MOCK-027" in response.reply
    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_list"


def test_handle_chat_guidance_returns_structured_resolution_advice(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.76)

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(orchestrator, "resolve_chat_guidance", lambda **kwargs: _authoritative_ticket_guidance(resolver_output))
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Structured guidance", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="What should I do for this ticket?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "resolution_advice"
    assert response.response_payload.ticket_id == "TW-MOCK-019"
    assert response.response_payload.recommended_actions
    assert response.response_payload.recommended_actions[0].reason
    assert response.response_payload.recommended_actions[0].evidence
    assert response.response_payload.confidence.level in {"medium", "high"}


def test_handle_chat_cause_query_returns_ranked_cause_analysis(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.78)

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: _authoritative_ticket_guidance(resolver_output, confidence_band="high"),
    )
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Cause analysis", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Why does this happen?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "cause_analysis"
    assert response.response_payload.ticket_id == "TW-MOCK-019"
    assert response.response_payload.possible_causes
    assert response.response_payload.possible_causes[0].evidence


def test_build_cause_analysis_payload_excludes_problem_rows_outside_selected_cluster() -> None:
    ticket = _ticket(
        ticket_id="TW-MOCK-019",
        title="CRM sync job stalls after token rotation",
        description="The CRM sync worker stops after token rotation.",
        status=TicketStatus.in_progress,
        priority=TicketPriority.high,
        category=TicketCategory.application,
        assignee="Nadia Boucher",
        reporter="Karim Benali",
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    resolver_output = _resolver_output(confidence=0.78, root_cause="Worker process did not reload rotated integration credentials")
    resolver_output.retrieval["evidence_clusters"] = {"selected_cluster_id": "crm_integration"}
    resolver_output.retrieval["related_problems"] = [
        {
            "id": "PB-VPN-01",
            "title": "VPN sessions time out after policy cleanup",
            "root_cause": "A recent VPN policy cleanup left the MFA session timeout and split-tunnel routes out of sync for several user groups.",
            "match_reason": "Direct semantic/lexical match from problem knowledge",
            "similarity_score": 0.93,
            "_advisor_cluster_id": "network_access",
        },
        {
            "id": "PB-CRM-01",
            "title": "CRM worker credential cache not refreshed",
            "root_cause": "The sync worker kept using the old integration credential after token rotation.",
            "match_reason": "Matches the CRM token-rotation incident family.",
            "similarity_score": 0.71,
            "_advisor_cluster_id": "crm_integration",
        },
    ]

    payload = build_cause_analysis_payload(ticket=ticket, resolver_output=resolver_output, lang="en")

    assert payload.type == "cause_analysis"
    combined_text = " ".join(
        [payload.summary]
        + [candidate.title for candidate in payload.possible_causes]
        + [candidate.explanation for candidate in payload.possible_causes]
    ).lower()
    assert "vpn" not in combined_text
    assert "mfa" not in combined_text
    assert "split-tunnel" not in combined_text
    assert payload.possible_causes[0].title == "Worker process did not reload rotated integration credentials"


def test_build_insufficient_evidence_payload_filters_recommended_checks_to_selected_family() -> None:
    ticket = _ticket(
        ticket_id="TW-MOCK-025",
        title="Payroll export writes invalid date columns",
        description="Payroll export produces broken date values.",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        category=TicketCategory.application,
        assignee="Karim Benali",
        reporter="Finance Lead",
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    resolver_output = _resolver_output(confidence=0.41, root_cause="Payroll export date serialization drift")
    resolver_output.retrieval["query_context"] = {
        "query": "Payroll export writes invalid date columns",
        "title": "Payroll export writes invalid date columns",
        "topics": ["payroll_export", "notification_distribution"],
        "domains": ["application"],
        "metadata": {"category": "application"},
    }
    resolver_output.retrieval["evidence_clusters"] = {
        "selected_cluster_id": "payroll_export",
        "clusters": [
            {"cluster_id": "payroll_export", "dominant_topic": "payroll_export"},
            {"cluster_id": "notification_distribution", "dominant_topic": "notification_distribution"},
        ],
    }
    resolver_output.validation_steps = [
        "Send one controlled approval notice and confirm it reaches the expected manager recipient.",
        "Generate one control export and validate the corrected date columns in the downstream import.",
    ]
    resolver_output.next_best_actions = [
        "Verify the payroll approval notification distribution rule and confirm the expected manager recipient mapping.",
        "Verify the payroll export formatter and the date-column mapping before the next import.",
    ]
    resolver_output.fallback_action = "Verify the distribution rule or recipient mapping with a controlled test."

    payload = build_insufficient_evidence_payload(resolver_output=resolver_output, ticket=ticket, lang="en")

    assert payload.type == "insufficient_evidence"
    assert payload.recommended_next_checks
    combined_text = " ".join(payload.recommended_next_checks).lower()
    assert "export" in combined_text or "date" in combined_text
    assert "recipient" not in combined_text
    assert "approval notice" not in combined_text


def test_handle_chat_similar_ticket_query_returns_structured_matches(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]
    resolver_output = _resolver_output(confidence=0.74)

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(orchestrator, "resolve_chat_guidance", lambda **kwargs: _authoritative_ticket_guidance(resolver_output))
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Similar matches", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Which tickets are similar to this one?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "similar_tickets"
    assert response.response_payload.source_ticket_id == "TW-MOCK-019"
    assert len(response.response_payload.matches) >= 1


def test_handle_chat_high_sla_query_returns_filtered_ticket_list(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-010",
            title="Messaging gateway queue saturation",
            description="Queue backlog keeps increasing.",
            status=TicketStatus.open,
            priority=TicketPriority.critical,
            category=TicketCategory.email,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
            sla_status="breached",
        ),
        _ticket(
            ticket_id="TW-MOCK-011",
            title="VPN tunnel re-auth loop",
            description="Users are repeatedly asked to re-authenticate.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.network,
            assignee="Youssef Hamdi",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=2),
            sla_status="at_risk",
        ),
        _ticket(
            ticket_id="TW-MOCK-012",
            title="HR export date formatting defect",
            description="Export still works but date format is wrong.",
            status=TicketStatus.open,
            priority=TicketPriority.medium,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=3),
            sla_status="ok",
        ),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(
        orchestrator,
        "list_assignees",
        lambda db: [SimpleNamespace(name="Nadia Boucher"), SimpleNamespace(name="Youssef Hamdi")],
    )
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    payload = ChatRequest(messages=[ChatMessage(role="user", content="Show me all high SLA tickets")], locale="en")
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "ticket_list"
    assert response.response_payload.list_kind == "high_sla_risk"
    assert {row.ticket_id for row in response.response_payload.tickets} == {"TW-MOCK-010", "TW-MOCK-011"}
    assert response.response_payload.total_count == 2


def test_handle_chat_weak_evidence_returns_insufficient_evidence_payload(monkeypatch) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    tickets = [
        _ticket(
            ticket_id="TW-MOCK-019",
            title="CRM sync job stalls after token rotation",
            description="The CRM sync worker stops after token rotation.",
            status=TicketStatus.in_progress,
            priority=TicketPriority.high,
            category=TicketCategory.application,
            assignee="Nadia Boucher",
            reporter="Karim Benali",
            created_at=now - dt.timedelta(hours=1),
        ),
    ]
    resolver_output = ResolverOutput(
        mode="informational",
        retrieval_query="CRM sync job stalls after token rotation",
        retrieval={
            "query_context": {"query": "CRM sync job stalls after token rotation"},
            "similar_tickets": [],
            "kb_articles": [],
            "solution_recommendations": [],
            "related_problems": [],
            "confidence": 0.18,
            "source": "fallback_rules",
        },
        advice=None,
        recommended_action=None,
        reasoning=None,
        match_summary=None,
        root_cause=None,
        supporting_context="Only weak lexical overlap was found.",
        why_this_matches=[],
        evidence_sources=[],
        next_best_actions=["Capture one fresh worker log excerpt after the next stall."],
        workflow_steps=[],
        validation_steps=["Confirm whether the rotated token was loaded by the worker process."],
        fallback_action="Capture one fresh worker log excerpt after the next stall.",
        confidence=0.18,
        missing_information=["No confirmed matching root cause was retrieved."],
    )

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(
        orchestrator,
        "resolve_chat_guidance",
        lambda **kwargs: _authoritative_ticket_guidance(
            resolver_output,
            confidence_band="low",
            degraded=True,
        ),
    )
    monkeypatch.setattr(orchestrator, "build_chat_reply", lambda *args, **kwargs: ("Insufficient evidence", None, None))

    payload = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="What should I do for this ticket?"),
        ],
        locale="en",
    )
    current_user = SimpleNamespace(role=UserRole.agent, name="Agent One")
    response = orchestrator.handle_chat(payload, db=None, current_user=current_user)

    assert response.response_payload is not None
    assert response.response_payload.type == "insufficient_evidence"
    assert response.response_payload.known_facts
    assert response.response_payload.recommended_next_checks
