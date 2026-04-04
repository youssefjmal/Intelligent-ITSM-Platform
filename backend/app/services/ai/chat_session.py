"""Deterministic chat-session helpers for safe follow-up resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.intents import _normalize_intent_text
from app.services.ai.conversation_policy import (
    CAUSE_HINTS as _CAUSE_HINTS,
    COMPARISON_HINTS as _COMPARISON_HINTS,
    DETAIL_HINTS as _DETAIL_HINTS,
    GUIDANCE_HINTS as _GUIDANCE_HINTS,
    IMPLICIT_REFERENCE_HINTS as _IMPLICIT_REFERENCE_HINTS,
    LIST_HINTS as _LIST_HINTS,
    MAX_RECENT_CHAT_TURNS,
    ORDINAL_HINTS as _ORDINAL_HINTS,
    SHORT_FOLLOWUP_HINTS as _SHORT_FOLLOWUP_HINTS,
    SIMILAR_HINTS as _SIMILAR_HINTS,
)
from app.services.ai.taxonomy import TOPIC_HINTS as _TOPIC_HINTS

_CHAT_TICKET_ID_RE = re.compile(r"\bTW-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
_CHAT_PROBLEM_ID_RE = re.compile(r"\bPB-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _message_attr(message: Any, name: str) -> Any:
    if isinstance(message, dict):
        return message.get(name)
    return getattr(message, name, None)


def _message_role(message: Any) -> str:
    return _normalize_text(_message_attr(message, "role")).lower()


def _message_content(message: Any) -> str:
    return _normalize_text(_message_attr(message, "content"))


def _message_response_payload_type(message: Any) -> str | None:
    return _normalize_text(_message_attr(message, "response_payload_type")) or None


def _message_entity_kind(message: Any) -> str | None:
    return _normalize_text(_message_attr(message, "entity_kind")).lower() or None


def _message_entity_id(message: Any) -> str | None:
    value = _normalize_text(_message_attr(message, "entity_id"))
    return value.upper() if value else None


def _message_inventory_kind(message: Any) -> str | None:
    return _normalize_text(_message_attr(message, "inventory_kind")).lower() or None


def _message_listed_entity_ids(message: Any) -> list[str]:
    raw = _message_attr(message, "listed_entity_ids")
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        current = _normalize_text(item).upper()
        if current:
            values.append(current)
    return values


def _extract_unique_ticket_ids(text: str) -> list[str]:
    matches = _CHAT_TICKET_ID_RE.findall(str(text or ""))
    unique: list[str] = []
    seen: set[str] = set()
    for match in matches:
        current = str(match or "").strip().upper()
        if not current or current in seen:
            continue
        seen.add(current)
        unique.append(current)
    return unique


def _extract_unique_problem_ids(text: str) -> list[str]:
    matches = _CHAT_PROBLEM_ID_RE.findall(str(text or ""))
    unique: list[str] = []
    seen: set[str] = set()
    for match in matches:
        current = str(match or "").strip().upper()
        if not current or current in seen:
            continue
        seen.add(current)
        unique.append(current)
    return unique


def _contains_any(text: str, hints: set[str]) -> bool:
    return any(hint in text for hint in hints)


def _detect_intent(text: str, *, role: str) -> str:
    normalized = _normalize_intent_text(text)
    if role == "assistant":
        if len(_extract_unique_ticket_ids(text)) > 1:
            return "list"
        if _contains_any(normalized, _COMPARISON_HINTS):
            return "compare"
        return "assistant"
    if _contains_any(normalized, _COMPARISON_HINTS):
        return "compare"
    if _contains_any(normalized, _CAUSE_HINTS):
        return "cause_analysis"
    if _contains_any(normalized, _GUIDANCE_HINTS):
        return "resolution_advice"
    if _contains_any(normalized, _SIMILAR_HINTS):
        return "similar_tickets"
    if _contains_any(normalized, _DETAIL_HINTS):
        return "ticket_details"
    if "ticket" in normalized and _contains_any(normalized, _LIST_HINTS):
        return "ticket_list"
    return "general"


def _detect_response_type(text: str, *, role: str, ticket_ids: list[str], detected_intent: str) -> str | None:
    normalized = _normalize_intent_text(text)
    if detected_intent == "compare" and len(ticket_ids) >= 2:
        return "ticket_comparison"
    if role == "assistant" and len(ticket_ids) > 1:
        return "ticket_list"
    if _contains_any(normalized, {"status", "statut", "etat"}):
        return "ticket_status"
    if _contains_any(normalized, _CAUSE_HINTS):
        return "cause_analysis"
    if _contains_any(normalized, _GUIDANCE_HINTS):
        return "resolution_advice"
    if ticket_ids:
        return "ticket_details"
    return None


def _detect_topic(text: str) -> str | None:
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", _normalize_intent_text(text)))
    for topic, hints in _TOPIC_HINTS.items():
        if tokens.intersection(hints):
            return topic
    return None


def _is_short_followup(text: str) -> bool:
    normalized = _normalize_intent_text(text)
    if normalized in _SHORT_FOLLOWUP_HINTS:
        return True
    return len(normalized.split()) <= 6 and (
        _contains_any(normalized, _SHORT_FOLLOWUP_HINTS)
        or normalized in {"why", "why?", "and this one", "next", "what about the other one"}
    )


def _ticket_order_append(order: list[str], ticket_id: str) -> None:
    if ticket_id in order:
        order.remove(ticket_id)
    order.append(ticket_id)


def _previous_ticket_id(session: "ChatSession") -> str | None:
    distinct = [ticket_id for ticket_id in session.ticket_reference_order if ticket_id]
    if len(distinct) >= 2:
        return distinct[-2]
    if len(session.compared_ticket_ids) >= 2:
        return session.compared_ticket_ids[0]
    return None


@dataclass(slots=True)
class MessageTurn:
    role: str
    text: str
    detected_intent: str | None = None
    resolved_ticket_ids: list[str] = field(default_factory=list)
    response_type: str | None = None
    turn_index: int = 0
    timestamp: str | None = None


@dataclass(slots=True)
class ChatSession:
    last_ticket_id: str | None = None
    last_ticket_list: list[str] = field(default_factory=list)
    last_intent: str | None = None
    last_response_type: str | None = None
    last_related_ticket_ids: list[str] = field(default_factory=list)
    active_topic: str | None = None
    compared_ticket_ids: list[str] = field(default_factory=list)
    recent_messages: list[MessageTurn] = field(default_factory=list)
    conversation_summary: str | None = None
    ticket_reference_order: list[str] = field(default_factory=list)
    # ID of the last problem discussed in this session.
    # Used to resolve follow-up references like "show its linked tickets"
    # or "what's the workaround?" without repeating the problem ID.
    last_problem_id: str | None = None
    # List of problem IDs returned in the last problem listing response.
    # Used to resolve positional references like "tell me about the second one".
    last_problem_list: list[str] = field(default_factory=list)

    @property
    def messages(self) -> list[dict[str, str]]:
        return [{"role": turn.role, "content": turn.text} for turn in self.recent_messages]


def _is_list_request_intent(text: str, *, detected_intent: str) -> bool:
    normalized = _normalize_intent_text(text)
    if detected_intent in {"ticket_list", "similar_tickets"}:
        return True
    return "tickets" in normalized and any(token in normalized for token in {"show", "list", "similar", "related", "matching"})


def _record_active_ticket(session: ChatSession, ticket_id: str) -> None:
    normalized = _normalize_text(ticket_id).upper()
    if not normalized:
        return
    session.last_ticket_id = normalized
    _ticket_order_append(session.ticket_reference_order, normalized)


def append_recent_message(session: ChatSession, message: MessageTurn, *, max_turns: int = MAX_RECENT_CHAT_TURNS) -> ChatSession:
    session.recent_messages.append(message)
    return trim_recent_history(session, max_turns=max_turns)


def trim_recent_history(session: ChatSession, *, max_turns: int = MAX_RECENT_CHAT_TURNS) -> ChatSession:
    if max_turns > 0 and len(session.recent_messages) > max_turns:
        session.recent_messages = session.recent_messages[-max_turns:]
    return session


def summarize_conversation_if_needed(session: ChatSession, *, max_recent: int = MAX_RECENT_CHAT_TURNS) -> ChatSession:
    if len(session.recent_messages) < max_recent and session.conversation_summary:
        return session
    parts: list[str] = []
    if session.last_ticket_id:
        parts.append(f"current_ticket={session.last_ticket_id}")
    if session.last_ticket_list:
        parts.append(f"last_list={','.join(session.last_ticket_list[:4])}")
    if session.last_problem_id:
        parts.append(f"current_problem={session.last_problem_id}")
    if session.last_problem_list:
        parts.append(f"last_problem_list={','.join(session.last_problem_list[:4])}")
    if len(session.compared_ticket_ids) >= 2:
        parts.append(f"compare={session.compared_ticket_ids[0]}:{session.compared_ticket_ids[1]}")
    if session.active_topic:
        parts.append(f"topic={session.active_topic}")
    if session.last_intent:
        parts.append(f"last_intent={session.last_intent}")
    if session.last_response_type:
        parts.append(f"last_response={session.last_response_type}")
    session.conversation_summary = "; ".join(parts) or None
    return session


def build_chat_session(messages: Any, *, max_recent: int = MAX_RECENT_CHAT_TURNS) -> ChatSession:
    if isinstance(messages, ChatSession):
        return summarize_conversation_if_needed(trim_recent_history(messages, max_turns=max_recent), max_recent=max_recent)

    session = ChatSession()
    rows = list(messages or []) if isinstance(messages, (list, tuple)) else list(getattr(messages, "messages", None) or [])
    pending_ticket_list = False
    for index, raw in enumerate(rows, start=1):
        role = _message_role(raw)
        text = _message_content(raw)
        if not text:
            continue
        payload_type = _message_response_payload_type(raw)
        payload_entity_kind = _message_entity_kind(raw)
        payload_entity_id = _message_entity_id(raw)
        payload_inventory_kind = _message_inventory_kind(raw)
        payload_listed_entity_ids = _message_listed_entity_ids(raw)
        ticket_ids = _extract_unique_ticket_ids(text)
        detected_intent = _detect_intent(text, role=role)
        response_type = payload_type or _detect_response_type(text, role=role, ticket_ids=ticket_ids, detected_intent=detected_intent)
        append_recent_message(
            session,
            MessageTurn(
                role=role,
                text=text,
                detected_intent=detected_intent,
                resolved_ticket_ids=ticket_ids,
                response_type=response_type,
                turn_index=index,
            ),
            max_turns=max_recent,
        )
        if role == "user":
            session.last_intent = detected_intent
            pending_ticket_list = _is_list_request_intent(text, detected_intent=detected_intent)
        elif response_type:
            session.last_response_type = response_type
        if role == "user":
            if len(ticket_ids) == 1:
                _record_active_ticket(session, ticket_ids[0])
            elif len(ticket_ids) >= 2:
                if detected_intent == "compare":
                    session.compared_ticket_ids = ticket_ids[:2]
                    for ticket_id in ticket_ids[:2]:
                        _record_active_ticket(session, ticket_id)
                else:
                    session.last_ticket_list = ticket_ids[:8]
            else:
                resolved_ticket_id, _ = resolve_contextual_reference(text, session)
                if resolved_ticket_id:
                    _record_active_ticket(session, resolved_ticket_id)
                if detected_intent == "compare":
                    current_ticket, previous_ticket = resolve_comparison_targets(text, session)
                    if current_ticket and previous_ticket:
                        session.compared_ticket_ids = [previous_ticket, current_ticket]
        elif ticket_ids:
            if len(ticket_ids) > 1:
                session.last_related_ticket_ids = ticket_ids[:4]
                if pending_ticket_list:
                    session.last_ticket_list = ticket_ids[:8]
            pending_ticket_list = False
        elif role == "assistant" and pending_ticket_list:
            pending_ticket_list = False
        # Problem ID tracking — mirrors ticket ID tracking above
        problem_ids_in_msg = _extract_unique_problem_ids(text)
        if role == "user":
            if len(problem_ids_in_msg) == 1:
                session.last_problem_id = problem_ids_in_msg[0]
            elif len(problem_ids_in_msg) > 1:
                session.last_problem_list = problem_ids_in_msg[:8]
        elif role == "assistant":
            if len(problem_ids_in_msg) > 1:
                session.last_problem_list = problem_ids_in_msg[:8]
            elif len(problem_ids_in_msg) == 1:
                session.last_problem_id = problem_ids_in_msg[0]
        if payload_entity_kind == "ticket" and payload_entity_id:
            _record_active_ticket(session, payload_entity_id)
        elif payload_entity_kind == "problem" and payload_entity_id:
            session.last_problem_id = payload_entity_id
        if payload_inventory_kind == "tickets" and payload_listed_entity_ids:
            session.last_ticket_list = payload_listed_entity_ids[:8]
        elif payload_inventory_kind == "problems" and payload_listed_entity_ids:
            session.last_problem_list = payload_listed_entity_ids[:8]
        topic = _detect_topic(text)
        if topic:
            session.active_topic = topic

    if not session.compared_ticket_ids:
        previous_ticket = _previous_ticket_id(session)
        if session.last_ticket_id and previous_ticket and previous_ticket != session.last_ticket_id:
            session.compared_ticket_ids = [previous_ticket, session.last_ticket_id]
    return summarize_conversation_if_needed(session, max_recent=max_recent)


def resolve_list_reference(text: str, session: ChatSession) -> tuple[str | None, str]:
    normalized = _normalize_intent_text(text)
    if not session.last_ticket_list:
        return None, "none"
    for index, hints in _ORDINAL_HINTS.items():
        if any(hint in normalized for hint in hints):
            if index < len(session.last_ticket_list):
                return session.last_ticket_list[index], "list_position"
            return None, "ambiguous"
    if any(token in normalized for token in {"last one", "last ticket", "dernier", "derniere"}):
        return session.last_ticket_list[-1], "list_position"
    if "other one" in normalized and len(session.last_ticket_list) == 2:
        if session.last_ticket_id and session.last_ticket_id in session.last_ticket_list:
            for ticket_id in session.last_ticket_list:
                if ticket_id != session.last_ticket_id:
                    return ticket_id, "list_position"
        return session.last_ticket_list[1], "list_position"
    return None, "none"


def resolve_contextual_reference(text: str, session: ChatSession) -> tuple[str | None, str]:
    """Resolve contextual references to tickets in the chat session.

    Handles list-position references, previous-ticket references, comparison
    context references, and implicit references to the last discussed ticket.
    For problem references, see resolve_problem_contextual_reference.

    Args:
        text: User message to resolve.
        session: Current chat session with ticket context.
    Returns:
        Tuple of (ticket_id or None, source_str).
    """
    list_ticket_id, list_source = resolve_list_reference(text, session)
    if list_ticket_id:
        return list_ticket_id, list_source

    normalized = _normalize_intent_text(text)
    if "previous one" in normalized or "previous ticket" in normalized or "preceding" in normalized:
        previous_ticket = _previous_ticket_id(session)
        if previous_ticket:
            return previous_ticket, "previous"
        return None, "ambiguous"

    if "other one" in normalized and len(session.compared_ticket_ids) >= 2 and session.last_ticket_id:
        for ticket_id in reversed(session.compared_ticket_ids):
            if ticket_id != session.last_ticket_id:
                return ticket_id, "comparison_context"

    if (
        _contains_any(normalized, _IMPLICIT_REFERENCE_HINTS)
        or _is_short_followup(text)
        or _contains_any(normalized, _DETAIL_HINTS.union(_GUIDANCE_HINTS).union(_CAUSE_HINTS).union(_SIMILAR_HINTS))
    ):
        if session.last_ticket_id:
            return session.last_ticket_id, "context"
    return None, "none"


def resolve_comparison_targets(text: str, session: ChatSession) -> tuple[str | None, str | None]:
    normalized = _normalize_intent_text(text)
    if not _contains_any(normalized, _COMPARISON_HINTS):
        return None, None

    explicit_ids = _extract_unique_ticket_ids(text)
    if len(explicit_ids) >= 2:
        return explicit_ids[0], explicit_ids[1]

    previous_ticket = _previous_ticket_id(session)
    current_ticket = explicit_ids[0] if explicit_ids else session.last_ticket_id
    if "other one" in normalized and len(session.last_ticket_list) == 2 and current_ticket in session.last_ticket_list:
        other_ticket = next((ticket_id for ticket_id in session.last_ticket_list if ticket_id != current_ticket), None)
        return current_ticket, other_ticket
    if current_ticket and previous_ticket and current_ticket != previous_ticket:
        return current_ticket, previous_ticket
    if len(session.compared_ticket_ids) >= 2:
        return session.compared_ticket_ids[-1], session.compared_ticket_ids[0]
    return None, None


def resolve_problem_contextual_reference(text: str, session: ChatSession) -> tuple[str | None, str]:
    """Resolve contextual references to problems in the chat session.

    Resolves implicit references like "this problem", ordinal references
    like "the first one" when a problem list is active, and positional
    references within session.last_problem_list.

    Args:
        text: User message to resolve.
        session: Current chat session with problem context.
    Returns:
        Tuple of (problem_id or None, source_str). source_str is one of:
        "explicit", "problem_context", "list_position", "ambiguous", "none".
    """
    normalized = _normalize_intent_text(text)

    # Ordinal references when a problem list is in context
    if session.last_problem_list:
        for index, hints in _ORDINAL_HINTS.items():
            if any(hint in normalized for hint in hints):
                if index < len(session.last_problem_list):
                    return session.last_problem_list[index], "list_position"
                return None, "ambiguous"

    # Implicit references to the last discussed problem
    problem_implicit = {"this problem", "ce probleme", "le probleme", "that problem", "the problem"}
    if _contains_any(normalized, problem_implicit):
        if session.last_problem_id:
            return session.last_problem_id, "problem_context"

    problem_followup_hints = {
        "workaround",
        "fix",
        "fixed",
        "resolved",
        "resolution",
        "remediation",
        "recommendation",
        "recommendations",
        "linked ticket",
        "linked tickets",
        "related problem",
        "root cause",
        "cause",
        "why",
        "pourquoi",
        "is it",
        "still open",
        "closed",
        "status",
        "statut",
    }
    if session.last_problem_id and (
        _is_short_followup(text)
        or _contains_any(normalized, problem_followup_hints)
        or _contains_any(normalized, _CAUSE_HINTS.union(_GUIDANCE_HINTS).union(_DETAIL_HINTS))
    ):
        return session.last_problem_id, "problem_context"

    return None, "none"


def build_relevant_history_context(session: ChatSession, *, question: str) -> str:
    normalized = _normalize_intent_text(question)
    lines: list[str] = []
    if session.last_ticket_id and not _extract_unique_ticket_ids(question):
        lines.append(f"current_ticket={session.last_ticket_id}")
    if session.last_ticket_list and any(token in normalized for token in {"second one", "third one", "other one", "last one"}):
        lines.append(f"last_ticket_list={','.join(session.last_ticket_list[:4])}")
    if len(session.compared_ticket_ids) >= 2 and _contains_any(normalized, _COMPARISON_HINTS):
        lines.append(f"compare_pair={session.compared_ticket_ids[1]}:{session.compared_ticket_ids[0]}")
    if session.active_topic and (_is_short_followup(question) or not _extract_unique_ticket_ids(question)):
        lines.append(f"active_topic={session.active_topic}")
    if session.conversation_summary:
        lines.append(f"summary={session.conversation_summary}")
    return "\n".join(lines[:4]).strip()
