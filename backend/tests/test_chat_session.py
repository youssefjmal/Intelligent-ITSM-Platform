from __future__ import annotations

from app.schemas.ai import ChatMessage
from app.services.ai.chat_session import (
    build_chat_session,
    resolve_comparison_targets,
    resolve_contextual_reference,
    resolve_list_reference,
)


def test_build_chat_session_trims_recent_history_and_keeps_summary() -> None:
    messages = [
        ChatMessage(role="user", content=f"Show me details of TW-MOCK-{index:03d}")
        for index in range(1, 11)
    ]

    session = build_chat_session(messages, max_recent=6)

    assert len(session.recent_messages) == 6
    assert session.last_ticket_id == "TW-MOCK-010"
    assert session.conversation_summary is not None
    assert "current_ticket=TW-MOCK-010" in session.conversation_summary


def test_resolve_contextual_reference_supports_second_one_and_previous_one() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="assistant", content="Matching tickets: TW-MOCK-010 TW-MOCK-011 TW-MOCK-012"),
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-025 details:"),
        ]
    )

    second_ticket, second_source = resolve_list_reference("Show me the second one", session)
    previous_ticket, previous_source = resolve_contextual_reference("Show me the previous one", session)

    assert second_ticket == "TW-MOCK-011"
    assert second_source == "list_position"
    assert previous_ticket == "TW-MOCK-019"
    assert previous_source == "previous"


def test_resolve_comparison_targets_uses_last_two_ticket_mentions() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="Show me details of TW-MOCK-019"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-019 details:"),
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(role="assistant", content="Ticket TW-MOCK-025 details:"),
        ]
    )

    current_ticket, previous_ticket = resolve_comparison_targets("Compare it with the previous one", session)

    assert current_ticket == "TW-MOCK-025"
    assert previous_ticket == "TW-MOCK-019"
