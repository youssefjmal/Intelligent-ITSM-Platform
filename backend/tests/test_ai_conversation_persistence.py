from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.chat_conversation import ChatConversation, ChatConversationMessage
from app.routers import ai as ai_router
from app.schemas.ai import (
    AIDraftContext,
    AISuggestedKBArticle,
    AISuggestionBundle,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    TicketDraft,
)


class _FakeConversationQuery:
    def __init__(self, db: "_FakeDB", model) -> None:  # noqa: ANN001
        self.db = db
        self.model = model
        self.filters: dict[str, object] = {}
        self._offset = 0
        self._limit: int | None = None

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def order_by(self, *_args):
        return self

    def offset(self, value: int):
        self._offset = value
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def first(self):
        rows = self._matching_rows()
        return rows[0] if rows else None

    def all(self):
        rows = self._matching_rows()
        if self.model is ChatConversation:
            rows = sorted(rows, key=lambda item: item.updated_at, reverse=True)
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def _matching_rows(self):
        if self.model is ChatConversation:
            rows = list(self.db.conversations)
        elif self.model is ChatConversationMessage:
            rows = [message for conv in self.db.conversations for message in conv.messages]
        else:
            rows = []
        for key, value in self.filters.items():
            rows = [row for row in rows if getattr(row, key) == value]
        return rows


class _FakeDB:
    def __init__(self, conversations: list[ChatConversation] | None = None) -> None:
        self.conversations = conversations or []
        self.rollback_called = False

    def query(self, model):  # noqa: ANN001
        return _FakeConversationQuery(self, model)

    def add(self, obj) -> None:  # noqa: ANN001
        if isinstance(obj, ChatConversation):
            if getattr(obj, "messages", None) is None:
                obj.messages = []
            if all(existing.id != obj.id for existing in self.conversations):
                self.conversations.append(obj)
            return
        if isinstance(obj, ChatConversationMessage):
            if obj.created_at is None:
                obj.created_at = dt.datetime.now(dt.timezone.utc)
            conv = next(item for item in self.conversations if item.id == obj.conversation_id)
            conv.messages.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self.rollback_called = True


def _conversation(conv_id: str, updated_at: dt.datetime, *, user_id: str = "user-1") -> ChatConversation:
    conv = ChatConversation(
        id=conv_id,
        user_id=user_id,
        title=f"Conversation {conv_id}",
        created_at=updated_at,
        updated_at=updated_at,
    )
    conv.messages = []
    return conv


def test_chat_persists_actions_for_history_restore(monkeypatch) -> None:
    db = _FakeDB()
    current_user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(
        ai_router,
        "handle_chat",
        lambda payload, db, current_user: ChatResponse(
            reply="Here is the answer",
            actions=["Open the ticket", "Check the SLA"],
        ),
    )

    response = ai_router.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="Help me with TEAMWILL-88")]),
        db=db,
        current_user=current_user,
    )

    restored = ai_router.get_conversation_messages(
        response.conversation_id,
        db=db,
        current_user=current_user,
    )

    assert restored[-1].role == "assistant"
    assert restored[-1].actions == ["Open the ticket", "Check the SLA"]


def test_chat_persists_ticket_and_draft_context_fields(monkeypatch) -> None:
    db = _FakeDB()
    current_user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(
        ai_router,
        "handle_chat",
        lambda payload, db, current_user: ChatResponse(
            reply="Draft ready",
            action="create_ticket",
            rag_grounding=True,
            ticket=TicketDraft(
                title="VPN access request",
                description="User needs VPN access",
                priority="medium",
                ticket_type="service_request",
                category="service_request",
                tags=[],
                assignee="Ops",
            ),
            draft_context=AIDraftContext(
                pre_filled_description="User needs VPN access",
                suggested_priority="medium",
                related_tickets=["TW-1"],
                confidence=0.8,
            ),
        ),
    )

    response = ai_router.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="Create a VPN access request")]),
        db=db,
        current_user=current_user,
    )

    restored = ai_router.get_conversation_messages(
        response.conversation_id,
        db=db,
        current_user=current_user,
    )

    assert restored[-1].action == "create_ticket"
    assert restored[-1].rag_grounding is True
    assert restored[-1].ticket is not None
    assert restored[-1].draft_context is not None


def test_chat_persists_kb_only_suggestions(monkeypatch) -> None:
    db = _FakeDB()
    current_user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(
        ai_router,
        "handle_chat",
        lambda payload, db, current_user: ChatResponse(
            reply="See this KB article",
            suggestions=AISuggestionBundle(
                kb_articles=[
                    AISuggestedKBArticle(
                        id="kb-1",
                        title="VPN troubleshooting",
                        excerpt="Restart the VPN service.",
                        similarity_score=0.8,
                    )
                ],
                confidence=0.8,
                source="hybrid",
            ),
        ),
    )

    response = ai_router.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="How do I fix VPN?")]),
        db=db,
        current_user=current_user,
    )

    restored = ai_router.get_conversation_messages(
        response.conversation_id,
        db=db,
        current_user=current_user,
    )

    assert restored[-1].suggestions.kb_articles
    assert restored[-1].suggestions.kb_articles[0].id == "kb-1"


def test_chat_updates_parent_conversation_timestamp_for_sorting(monkeypatch) -> None:
    older = _conversation(
        "conv-older",
        dt.datetime(2026, 4, 18, 8, 0, tzinfo=dt.timezone.utc),
    )
    newer = _conversation(
        "conv-newer",
        dt.datetime(2026, 4, 19, 9, 0, tzinfo=dt.timezone.utc),
    )
    db = _FakeDB([older, newer])
    current_user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(
        ai_router,
        "handle_chat",
        lambda payload, db, current_user: ChatResponse(reply="Follow-up reply"),
    )

    original_updated_at = older.updated_at
    ai_router.chat(
        ChatRequest(
            conversation_id="conv-older",
            messages=[ChatMessage(role="user", content="Follow up on the older conversation")],
        ),
        db=db,
        current_user=current_user,
    )

    conversations = ai_router.list_conversations(limit=20, offset=0, db=db, current_user=current_user)

    assert older.updated_at > original_updated_at
    assert conversations[0].id == "conv-older"
