from __future__ import annotations

from app.schemas.ai import ChatMessage
from app.services.ai.chat_session import (
    build_chat_session,
    resolve_comparison_targets,
    resolve_contextual_reference,
    resolve_list_reference,
    resolve_problem_contextual_reference,
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
            ChatMessage(role="user", content="Show high SLA tickets"),
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


def test_build_chat_session_keeps_user_selected_ticket_sticky_despite_assistant_suggestions() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="Show me details of TW-MOCK-025"),
            ChatMessage(
                role="assistant",
                content=(
                    "Ticket TW-MOCK-025 details.\n"
                    "Related suggestions: TW-MOCK-013, TW-MOCK-032, TW-MOCK-008"
                ),
            ),
        ]
    )

    ticket_id, source = resolve_contextual_reference("What should I do next for this ticket?", session)

    assert session.last_ticket_id == "TW-MOCK-025"
    assert session.last_ticket_list == []
    assert ticket_id == "TW-MOCK-025"
    assert source == "context"


def test_build_chat_session_captures_assistant_list_only_after_user_requested_list() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="Show high SLA tickets"),
            ChatMessage(
                role="assistant",
                content=(
                    "Matching tickets:\n"
                    "- TW-MOCK-010\n"
                    "- TW-MOCK-011\n"
                    "- TW-MOCK-012"
                ),
            ),
        ]
    )

    second_ticket, source = resolve_list_reference("Show me the second one", session)

    assert session.last_ticket_id is None
    assert session.last_ticket_list == ["TW-MOCK-010", "TW-MOCK-011", "TW-MOCK-012"]
    assert second_ticket == "TW-MOCK-011"
    assert source == "list_position"


def test_build_chat_session_prefers_structured_payload_metadata_for_problem_context() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="current problems"),
            ChatMessage(
                role="assistant",
                content="3 problems found.",
                response_payload_type="problem_list",
                inventory_kind="problems",
                listed_entity_ids=["PB-MOCK-01", "PB-MOCK-02", "PB-MOCK-03"],
            ),
            ChatMessage(
                role="user",
                content="tell me about the second one",
            ),
        ]
    )

    problem_id, source = resolve_problem_contextual_reference("show me the second one", session)

    assert session.last_problem_list == ["PB-MOCK-01", "PB-MOCK-02", "PB-MOCK-03"]
    assert problem_id == "PB-MOCK-02"
    assert source == "list_position"


def test_build_chat_session_restores_ticket_list_from_problem_linked_tickets_payload() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="show linked tickets"),
            ChatMessage(
                role="assistant",
                content="2 linked tickets found.",
                response_payload_type="problem_linked_tickets",
                listed_entity_ids=["TW-MOCK-010", "TW-MOCK-011"],
            ),
        ]
    )

    ticket_id, source = resolve_list_reference("show me the second one", session)

    assert session.last_ticket_list == ["TW-MOCK-010", "TW-MOCK-011"]
    assert ticket_id == "TW-MOCK-011"
    assert source == "list_position"


def test_build_chat_session_restores_active_ticket_from_similar_tickets_payload() -> None:
    session = build_chat_session(
        [
            ChatMessage(
                role="assistant",
                content="Similar tickets for TW-MOCK-025",
                response_payload_type="similar_tickets",
                entity_id="TW-MOCK-025",
                listed_entity_ids=["TW-MOCK-010", "TW-MOCK-011"],
            ),
            ChatMessage(role="user", content="what should i do next for this ticket?"),
        ]
    )

    ticket_id, source = resolve_contextual_reference("what should i do next for this ticket?", session)

    assert session.last_ticket_id == "TW-MOCK-025"
    assert ticket_id == "TW-MOCK-025"
    assert source == "context"


def test_resolve_comparison_targets_supports_ordinals_from_last_list() -> None:
    session = build_chat_session(
        [
            ChatMessage(role="user", content="Show high SLA tickets"),
            ChatMessage(
                role="assistant",
                content="Matching tickets: TW-MOCK-010 TW-MOCK-011 TW-MOCK-012",
                response_payload_type="ticket_list",
                inventory_kind="tickets",
                listed_entity_ids=["TW-MOCK-010", "TW-MOCK-011", "TW-MOCK-012"],
            ),
        ]
    )

    current_ticket, previous_ticket = resolve_comparison_targets(
        "compare the first one with the second one",
        session,
    )

    assert current_ticket == "TW-MOCK-010"
    assert previous_ticket == "TW-MOCK-011"
