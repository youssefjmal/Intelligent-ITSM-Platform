from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.schemas.ai import ChatMessage, ChatRequest
from app.services.ai import intents, orchestrator
from app.services.ai.intents import ChatIntent


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
        assignment_change_count=0,
        first_action_at=None,
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
