"""Deterministic chat-session helpers for safe follow-up resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.intents import _normalize_intent_text

_CHAT_TICKET_ID_RE = re.compile(r"\bTW-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)

_DETAIL_HINTS = {
    "status",
    "statut",
    "etat",
    "detail",
    "details",
    "summary",
    "resume",
    "info",
    "information",
}
_CAUSE_HINTS = {
    "root cause",
    "cause",
    "why",
    "pourquoi",
    "why did this happen",
    "why is this happening",
    "what caused this",
}
_GUIDANCE_HINTS = {
    "what should i do",
    "what do i do",
    "what should i do next",
    "recommended action",
    "next step",
    "next steps",
    "how do i fix",
    "how do i resolve",
    "how should i fix",
    "how should i resolve",
    "how to fix",
    "how to resolve",
}
_SIMILAR_HINTS = {
    "similar ticket",
    "similar tickets",
    "related ticket",
    "related tickets",
    "other one",
}
_LIST_HINTS = {
    "list",
    "show me",
    "show",
    "tickets",
    "critical tickets",
    "high sla tickets",
    "active tickets",
}
_IMPLICIT_REFERENCE_HINTS = {
    "this ticket",
    "that ticket",
    "the ticket",
    "this issue",
    "that issue",
    "this incident",
    "that incident",
    "and this one",
    "what about this one",
}
_SHORT_FOLLOWUP_HINTS = {
    "why",
    "why?",
    "what about the other one",
    "and this one",
    "what should i do next",
    "what should i do",
    "what do i do",
    "next",
}
_COMPARISON_HINTS = {
    "compare",
    "comparison",
    "versus",
    "vs",
    "difference",
    "previous one",
}
_TOPIC_HINTS = {
    "crm_integration": {"crm", "sync", "token", "oauth", "credential", "worker", "integration", "scheduler"},
    "payroll_export": {"payroll", "export", "csv", "date", "formatter", "parser", "mapping", "schema"},
    "mail_transport": {"mail", "email", "relay", "connector", "mailbox", "forwarding", "distribution"},
    "network_access": {"vpn", "dns", "route", "routing", "gateway", "remote", "tunnel", "mfa"},
}
_ORDINAL_HINTS = {
    0: ("first one", "1st one", "first ticket", "premier", "premiere", "le premier"),
    1: ("second one", "2nd one", "second ticket", "deuxieme", "la deuxieme", "le deuxieme"),
    2: ("third one", "3rd one", "third ticket", "troisieme", "la troisieme", "le troisieme"),
}


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

    @property
    def messages(self) -> list[dict[str, str]]:
        return [{"role": turn.role, "content": turn.text} for turn in self.recent_messages]


def append_recent_message(session: ChatSession, message: MessageTurn, *, max_turns: int = 8) -> ChatSession:
    session.recent_messages.append(message)
    return trim_recent_history(session, max_turns=max_turns)


def trim_recent_history(session: ChatSession, *, max_turns: int = 8) -> ChatSession:
    if max_turns > 0 and len(session.recent_messages) > max_turns:
        session.recent_messages = session.recent_messages[-max_turns:]
    return session


def summarize_conversation_if_needed(session: ChatSession, *, max_recent: int = 8) -> ChatSession:
    if len(session.recent_messages) < max_recent and session.conversation_summary:
        return session
    parts: list[str] = []
    if session.last_ticket_id:
        parts.append(f"current_ticket={session.last_ticket_id}")
    if session.last_ticket_list:
        parts.append(f"last_list={','.join(session.last_ticket_list[:4])}")
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


def build_chat_session(messages: Any, *, max_recent: int = 8) -> ChatSession:
    if isinstance(messages, ChatSession):
        return summarize_conversation_if_needed(trim_recent_history(messages, max_turns=max_recent), max_recent=max_recent)

    session = ChatSession()
    rows = list(messages or []) if isinstance(messages, (list, tuple)) else list(getattr(messages, "messages", None) or [])
    for index, raw in enumerate(rows, start=1):
        role = _message_role(raw)
        text = _message_content(raw)
        if not text:
            continue
        ticket_ids = _extract_unique_ticket_ids(text)
        detected_intent = _detect_intent(text, role=role)
        response_type = _detect_response_type(text, role=role, ticket_ids=ticket_ids, detected_intent=detected_intent)
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
        elif response_type:
            session.last_response_type = response_type
        if ticket_ids:
            for ticket_id in ticket_ids:
                _ticket_order_append(session.ticket_reference_order, ticket_id)
            if len(ticket_ids) == 1:
                session.last_ticket_id = ticket_ids[0]
            else:
                session.last_ticket_list = ticket_ids[:8]
                session.last_related_ticket_ids = ticket_ids[1:4]
                if detected_intent == "compare":
                    session.compared_ticket_ids = ticket_ids[:2]
        elif detected_intent == "compare":
            previous_ticket = _previous_ticket_id(session)
            if session.last_ticket_id and previous_ticket and previous_ticket != session.last_ticket_id:
                session.compared_ticket_ids = [previous_ticket, session.last_ticket_id]
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

    if _contains_any(normalized, _IMPLICIT_REFERENCE_HINTS) or _is_short_followup(text) or _contains_any(normalized, _DETAIL_HINTS.union(_GUIDANCE_HINTS).union(_CAUSE_HINTS)):
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
