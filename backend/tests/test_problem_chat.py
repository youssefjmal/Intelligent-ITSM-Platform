"""
Tests for problem chat intent detection and routing.

Coverage:
  1. Problem listing intent (FR)
  2. Problem listing intent (EN)
  3. Known error status filter extraction
  4. Problem detail by explicit ID
  5. Problem drill-down follow-up
  6. Problem not found
  7. Recommendation listing intent
  8. False positive guard — "no problems with this implementation"
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType, UserRole
from app.schemas.ai import ChatMessage, ChatRequest
from app.services.ai.intents import (
    ChatIntent,
    IntentConfidence,
    detect_intent_with_confidence,
    extract_problem_id,
    extract_status_filter,
    _normalize_intent_text,
)
from app.services.ai import orchestrator


# ---------------------------------------------------------------------------
# 1. Problem listing intent — French
# ---------------------------------------------------------------------------


def test_problem_listing_intent_fr():
    """'quels sont les problemes' maps to problem_listing with high confidence."""
    intent, confidence = detect_intent_with_confidence("quels sont les problèmes")
    assert intent == ChatIntent.problem_listing
    assert confidence == IntentConfidence.high


# ---------------------------------------------------------------------------
# 2. Problem listing intent — English
# ---------------------------------------------------------------------------


def test_problem_listing_intent_en():
    """'show me problems' maps to problem_listing with high confidence."""
    intent, confidence = detect_intent_with_confidence("show me problems")
    assert intent == ChatIntent.problem_listing
    assert confidence == IntentConfidence.high


def test_problem_listing_intent_current_problems():
    """Natural inventory phrasing like 'current problems' should list problems."""
    intent, confidence = detect_intent_with_confidence("current problems")
    assert intent == ChatIntent.problem_listing
    assert confidence == IntentConfidence.high


# ---------------------------------------------------------------------------
# 3. Known error status filter extraction
# ---------------------------------------------------------------------------


def test_known_error_status_filter():
    """'show known errors' extracts status_filter='known_error'."""
    normalized = _normalize_intent_text("show known errors")
    status = extract_status_filter(normalized)
    assert status == "known_error"


# ---------------------------------------------------------------------------
# 4. Problem detail by explicit ID
# ---------------------------------------------------------------------------


def test_problem_detail_by_id():
    """A message containing PB-MOCK-01 maps to problem_detail."""
    intent, confidence = detect_intent_with_confidence("tell me about PB-MOCK-01")
    assert intent == ChatIntent.problem_detail
    assert confidence == IntentConfidence.high


def test_problem_analysis_query_by_id_prefers_general_guidance():
    """Cause/remediation questions with PB-* should use the richer guidance path."""
    intent, confidence = detect_intent_with_confidence("why is PB-MOCK-01 happening?")
    assert intent == ChatIntent.general
    assert confidence == IntentConfidence.high


# ---------------------------------------------------------------------------
# 5. Problem drill-down follow-up
# ---------------------------------------------------------------------------


def test_problem_drill_down_follow_up():
    """'show linked tickets' maps to problem_drill_down."""
    intent, confidence = detect_intent_with_confidence("show linked tickets")
    assert intent == ChatIntent.problem_drill_down
    assert confidence == IntentConfidence.high


def test_problem_drill_down_with_explicit_problem_id():
    """Explicit PB-* linked-ticket requests should stay on the drill-down route."""
    intent, confidence = detect_intent_with_confidence("show linked tickets for PB-MOCK-01")
    assert intent == ChatIntent.problem_drill_down
    assert confidence == IntentConfidence.high


# ---------------------------------------------------------------------------
# 6. Problem not found
# ---------------------------------------------------------------------------


def test_problem_not_found():
    """extract_problem_id returns None for message without PB-* pattern."""
    result = extract_problem_id("what is the status of this ticket?")
    assert result is None


# ---------------------------------------------------------------------------
# 7. Recommendation listing intent
# ---------------------------------------------------------------------------


def test_recommendation_listing_intent():
    """'show me recommendations' maps to recommendation_listing."""
    intent, confidence = detect_intent_with_confidence("show me recommendations")
    assert intent == ChatIntent.recommendation_listing
    assert confidence == IntentConfidence.high


def test_recommendation_listing_intent_current_recommendations():
    """Natural inventory phrasing like 'current recommendations' should list recommendations."""
    intent, confidence = detect_intent_with_confidence("current recommendations")
    assert intent == ChatIntent.recommendation_listing
    assert confidence == IntentConfidence.high


# ---------------------------------------------------------------------------
# 8. False positive guard
# ---------------------------------------------------------------------------


def test_problem_false_positive_guard():
    """'there are no problems with this implementation' must NOT trigger problem_listing."""
    intent, _ = detect_intent_with_confidence("there are no problems with this implementation")
    assert intent != ChatIntent.problem_listing


def _ticket(*, ticket_id: str, title: str, problem_id: str | None = None):
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        title=title,
        description=title,
        status=TicketStatus.open,
        priority=TicketPriority.high,
        category=TicketCategory.application,
        ticket_type=TicketType.incident,
        assignee="Nadia Boucher",
        reporter="Karim Benali",
        resolution=None,
        comments=[],
        tags=[],
        created_at=now,
        updated_at=now,
        jira_created_at=None,
        jira_updated_at=None,
        sla_status=None,
        sla_due_at=None,
        sla_remaining_minutes=None,
        sla_remaining_human=None,
        problem_id=problem_id,
        assignment_change_count=0,
        first_action_at=None,
        resolved_at=None,
    )


def test_handle_chat_problem_detail_enriches_with_probable_cause(monkeypatch):
    tickets = [
        _ticket(ticket_id="TW-MOCK-010", title="Mail forwarding failures after certificate renewal", problem_id="PB-MOCK-01"),
        _ticket(ticket_id="TW-MOCK-011", title="Unrelated VPN issue", problem_id=None),
    ]
    problem_obj = SimpleNamespace(
        id="PB-MOCK-01",
        title="Recurring mail forwarding delays",
        status="investigating",
        category="email",
        occurrences_count=4,
        active_count=1,
        root_cause=None,
        workaround=None,
        permanent_fix=None,
        last_seen_at=dt.datetime.now(dt.timezone.utc),
    )
    resolver_output = SimpleNamespace(
        advice=SimpleNamespace(
            root_cause=None,
            probable_root_cause="Mail workers are not refreshing the relay trust store consistently after certificate renewals.",
        ),
        root_cause=None,
    )

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets)
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(orchestrator, "get_problem", lambda db, problem_id: problem_obj if problem_id == "PB-MOCK-01" else None)
    monkeypatch.setattr(orchestrator, "resolve_problem_advice", lambda *args, **kwargs: resolver_output)

    response = orchestrator.handle_chat(
        ChatRequest(messages=[ChatMessage(role="user", content="tell me about PB-MOCK-01")], locale="en"),
        db=SimpleNamespace(),
        current_user=SimpleNamespace(role=UserRole.agent, name="Agent One"),
    )

    assert response.response_payload is not None
    assert response.response_payload.type == "problem_detail"
    assert response.response_payload.linked_ticket_count == 1
    assert response.response_payload.ai_probable_cause == resolver_output.advice.probable_root_cause


def test_handle_chat_problem_linked_tickets_uses_visible_ticket_scope(monkeypatch):
    tickets = [
        _ticket(ticket_id="TW-MOCK-010", title="Mail forwarding failures after certificate renewal", problem_id="PB-MOCK-01"),
        _ticket(ticket_id="TW-MOCK-011", title="Teams consumer backlog", problem_id="PB-MOCK-01"),
        _ticket(ticket_id="TW-MOCK-099", title="Hidden unrelated ticket", problem_id=None),
    ]

    monkeypatch.setattr(orchestrator, "list_tickets_for_user", lambda db, user: tickets[:2])
    monkeypatch.setattr(orchestrator, "list_assignees", lambda db: [SimpleNamespace(name="Nadia Boucher")])
    monkeypatch.setattr(orchestrator, "compute_stats", lambda rows: {"total": len(rows)})

    response = orchestrator.handle_chat(
        ChatRequest(
            messages=[
                ChatMessage(role="user", content="tell me about PB-MOCK-01"),
                ChatMessage(role="assistant", content="Problem PB-MOCK-01 details:"),
                ChatMessage(role="user", content="show linked tickets"),
            ],
            locale="en",
        ),
        db=SimpleNamespace(),
        current_user=SimpleNamespace(role=UserRole.agent, name="Agent One"),
    )

    assert response.response_payload is not None
    assert response.response_payload.type == "problem_linked_tickets"
    assert response.response_payload.problem_id == "PB-MOCK-01"
    assert response.response_payload.total_count == 2
    assert {row.id for row in response.response_payload.tickets} == {"TW-MOCK-010", "TW-MOCK-011"}


def test_resolve_chat_guidance_reuses_last_problem_context_for_follow_up(monkeypatch):
    tickets = [
        _ticket(ticket_id="TW-MOCK-010", title="Mail forwarding failures after certificate renewal", problem_id="PB-MOCK-01"),
    ]
    problem_obj = SimpleNamespace(id="PB-MOCK-01", title="Recurring mail forwarding delays")
    calls: dict[str, str] = {}

    monkeypatch.setattr(orchestrator, "get_problem", lambda db, problem_id: problem_obj if problem_id == "PB-MOCK-01" else None)
    def _fake_resolve_problem_advice(db, problem, **kwargs):
        calls["problem_id"] = problem.id
        return SimpleNamespace(advice=object())

    monkeypatch.setattr(orchestrator, "resolve_problem_advice", _fake_resolve_problem_advice)
    monkeypatch.setattr(
        orchestrator,
        "_build_chat_grounding",
        lambda **kwargs: SimpleNamespace(retrieval_mode="semantic", degraded=False),
    )

    session = orchestrator.build_chat_session(
        [
            ChatMessage(role="user", content="tell me about PB-MOCK-01"),
            ChatMessage(role="assistant", content="Problem PB-MOCK-01 details:"),
        ]
    )

    context = orchestrator.resolve_chat_guidance(
        question="what caused this?",
        lang="en",
        plan=orchestrator.RoutingPlan(
            name="general_llm",
            intent=ChatIntent.general,
            use_llm=True,
            use_kb=True,
        ),
        db=SimpleNamespace(),
        tickets=tickets,
        conversation_state=session,
        solution_quality="medium",
    )

    assert calls["problem_id"] == "PB-MOCK-01"
    assert context.entity_type == "problem"
    assert context.entity_id == "PB-MOCK-01"
