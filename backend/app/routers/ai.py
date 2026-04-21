"""AI endpoints backed by service-layer orchestration."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.deps import get_current_user, require_roles
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.chat_conversation import ChatConversation, ChatConversationMessage
from app.models.enums import UserRole
from app.schemas.ai import (
    AIFeedbackRequest,
    AIFeedbackResponse,
    AIRecommendationFeedbackSummaryWithBreakdown,
    ChatRequest,
    ChatResponse,
    ClassificationRequest,
    ClassificationResponse,
    ConversationMessageOut,
    ConversationOut,
    SuggestRequest,
    SuggestResponse,
)
from app.services.ai.feedback import (
    aggregate_agent_feedback_analytics,
    aggregate_feedback_counts,
    get_feedback_bundle_for_target,
    record_feedback,
    upsert_agent_feedback,
)
from app.services.embeddings import search_kb
from app.services.ai.orchestrator import handle_chat, handle_classify, handle_suggest

# Rate limiting for /api/ai/* is handled by the global middleware in
# core/rate_limit.py — no router-level dependency needed.
router = APIRouter(
    dependencies=[
        Depends(get_current_user),
        Depends(require_roles(UserRole.admin, UserRole.agent)),
    ]
)


@router.post("/classify", response_model=ClassificationResponse)
def classify(
    payload: ClassificationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ClassificationResponse:
    return handle_classify(payload, db, current_user=current_user)

 
@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ChatResponse:
    try:
        response = handle_chat(payload, db, current_user)
    except Exception as exc:
        logger.warning("handle_chat unhandled exception: %s", exc, exc_info=True)
        lang = "fr" if str(payload.locale or "").lower().startswith("fr") else "en"
        fallback_reply = (
            "Une erreur s'est produite. Veuillez reformuler votre question."
            if lang == "fr"
            else "An error occurred. Please rephrase your question."
        )
        return ChatResponse(reply=fallback_reply)

    # Persist the exchange to the user's conversation history.
    try:
        conv_id = payload.conversation_id
        if conv_id:
            conv = db.query(ChatConversation).filter_by(id=conv_id, user_id=str(current_user.id)).first()
        else:
            conv = None

        if conv is None:
            # Auto-title from first user message (truncated to 80 chars)
            first_user_text = next(
                (m.content for m in payload.messages if m.role == "user"), "New conversation"
            )
            title = first_user_text[:80].strip()
            conv = ChatConversation(
                id=str(uuid4()),
                user_id=str(current_user.id),
                title=title,
            )
            db.add(conv)
            db.flush()

        last_user = payload.messages[-1]
        db.add(ChatConversationMessage(
            id=str(uuid4()),
            conversation_id=conv.id,
            role="user",
            content=last_user.content,
        ))
        # Store rich rendering metadata so history loads restore full UI
        assistant_meta: dict = {}
        if response.action:
            assistant_meta["action"] = response.action
        if response.ticket is not None:
            try:
                assistant_meta["ticket"] = response.ticket.model_dump(mode="json")
            except Exception:
                pass
        if response.rag_grounding:
            assistant_meta["rag_grounding"] = True
        if response.resolution_advice is not None:
            try:
                assistant_meta["resolution_advice"] = response.resolution_advice.model_dump(mode="json")
            except Exception:
                pass
        if response.grounding is not None:
            try:
                assistant_meta["grounding"] = response.grounding.model_dump(mode="json")
            except Exception:
                pass
        if response.draft_context is not None:
            try:
                assistant_meta["draft_context"] = response.draft_context.model_dump(mode="json")
            except Exception:
                pass
        if response.actions:
            assistant_meta["actions"] = list(response.actions)
        if response.response_payload is not None:
            try:
                assistant_meta["response_payload"] = response.response_payload.model_dump(mode="json")
            except Exception:
                pass
        if response.ticket_results is not None:
            try:
                assistant_meta["ticket_results"] = response.ticket_results.model_dump(mode="json")
            except Exception:
                pass
        if response.suggestions and (
            response.suggestions.tickets
            or response.suggestions.problems
            or response.suggestions.kb_articles
            or response.suggestions.solution_recommendations
            or response.suggestions.resolution_advice
        ):
            try:
                assistant_meta["suggestions"] = response.suggestions.model_dump(mode="json")
            except Exception:
                pass
        db.add(ChatConversationMessage(
            id=str(uuid4()),
            conversation_id=conv.id,
            role="assistant",
            content=response.reply,
            msg_metadata=assistant_meta or None,
        ))
        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        db.add(conv)
        db.commit()
        response.conversation_id = conv.id
    except Exception as exc:
        logger.warning("Failed to persist chat conversation: %s", exc, exc_info=True)
        db.rollback()

    return response


# ---------------------------------------------------------------------------
# Conversation history CRUD
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[ConversationOut]:
    rows = (
        db.query(ChatConversation)
        .filter_by(user_id=str(current_user.id))
        .order_by(ChatConversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        ConversationOut(
            id=r.id,
            title=r.title,
            created_at=r.created_at,
            updated_at=r.updated_at,
            message_count=len(r.messages),
        )
        for r in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageOut])
def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[ConversationMessageOut]:
    conv = db.query(ChatConversation).filter_by(id=conversation_id, user_id=str(current_user.id)).first()
    if not conv:
        raise NotFoundError("conversation_not_found")
    from app.schemas.ai import (
        AIChatGrounding,
        AIChatStructuredResponse,
        AIChatTicketResults,
        AISuggestionBundle,
        AIResolutionAdvice,
        AIDraftContext,
        TicketDraft,
    )

    result = []
    for m in conv.messages:
        meta = m.msg_metadata or {}
        out = ConversationMessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
        if m.role == "assistant" and meta:
            out.action = str(meta.get("action") or "").strip() or None
            out.rag_grounding = bool(meta.get("rag_grounding", False))
            try:
                if "ticket" in meta:
                    out.ticket = TicketDraft.model_validate(meta["ticket"])
            except Exception:
                pass
            try:
                if "resolution_advice" in meta:
                    out.resolution_advice = AIResolutionAdvice.model_validate(meta["resolution_advice"])
            except Exception:
                pass
            try:
                if "grounding" in meta:
                    out.grounding = AIChatGrounding.model_validate(meta["grounding"])
            except Exception:
                pass
            try:
                if "draft_context" in meta:
                    out.draft_context = AIDraftContext.model_validate(meta["draft_context"])
            except Exception:
                pass
            try:
                if "response_payload" in meta:
                    out.response_payload = AIChatStructuredResponse.model_validate(meta["response_payload"])
            except Exception:
                pass
            try:
                if "ticket_results" in meta:
                    out.ticket_results = AIChatTicketResults.model_validate(meta["ticket_results"])
            except Exception:
                pass
            try:
                if "suggestions" in meta:
                    out.suggestions = AISuggestionBundle.model_validate(meta["suggestions"])
            except Exception:
                pass
            out.actions = meta.get("actions") or []
        result.append(out)
    return result


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Response:
    conv = db.query(ChatConversation).filter_by(id=conversation_id, user_id=str(current_user.id)).first()
    if not conv:
        raise NotFoundError("conversation_not_found")
    db.delete(conv)
    db.commit()
    return Response(status_code=204)


@router.post("/suggest", response_model=SuggestResponse)
def suggest(
    payload: SuggestRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> SuggestResponse:
    return handle_suggest(payload, db, current_user)


@router.post("/feedback", response_model=AIFeedbackResponse)
def submit_feedback(
    payload: AIFeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> AIFeedbackResponse:
    if payload.feedback_type:
        row = upsert_agent_feedback(
            db,
            user_id=getattr(current_user, "id", None),
            feedback_type=payload.feedback_type,
            source_surface=str(payload.source_surface or ""),
            ticket_id=payload.ticket_id,
            recommendation_id=payload.recommendation_id,
            answer_type=payload.answer_type,
            recommended_action=payload.recommended_action,
            display_mode=payload.display_mode,
            confidence=payload.confidence,
            reasoning=payload.reasoning,
            match_summary=payload.match_summary,
            evidence_count=payload.evidence_count,
            metadata=payload.metadata,
        )
        bundle = get_feedback_bundle_for_target(
            db,
            current_user_id=getattr(current_user, "id", None),
            source_surface=str(payload.source_surface or ""),
            ticket_id=payload.ticket_id,
            recommendation_id=payload.recommendation_id,
            answer_type=payload.answer_type,
        )
        return AIFeedbackResponse(
            status="recorded",
            source=row.source,
            source_id=row.source_id,
            ticket_id=row.ticket_id,
            recommendation_id=row.recommendation_id,
            source_surface=row.source_surface,
            current_feedback=bundle.get("current_feedback"),
            feedback_summary=bundle.get("feedback_summary"),
        )

    source = str(payload.source or "").strip().lower()
    source_id = str(payload.source_id or "").strip() or None
    row = record_feedback(
        db,
        user_id=getattr(current_user, "id", None),
        query=payload.query,
        recommendation_text=payload.recommendation_text,
        source=source,
        source_id=source_id,
        vote=payload.vote,
        context=payload.context,
    )
    counts = aggregate_feedback_counts(db, source=source, source_id=source_id)
    return AIFeedbackResponse(
        status="recorded",
        source=row.source,
        source_id=row.source_id,
        helpful_votes=int(counts["helpful"]),
        not_helpful_votes=int(counts["not_helpful"]),
    )


@router.get("/feedback/summary", response_model=AIFeedbackResponse)
def feedback_summary(
    ticket_id: str | None = Query(default=None, max_length=20),
    recommendation_id: str | None = Query(default=None, max_length=64),
    answer_type: str | None = Query(default=None, max_length=32),
    source_surface: str = Query(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> AIFeedbackResponse:
    bundle = get_feedback_bundle_for_target(
        db,
        current_user_id=getattr(current_user, "id", None),
        source_surface=source_surface,
        ticket_id=ticket_id,
        recommendation_id=recommendation_id,
        answer_type=answer_type,
    )
    return AIFeedbackResponse(
        status="ok",
        ticket_id=ticket_id,
        recommendation_id=recommendation_id,
        source_surface=source_surface,
        current_feedback=bundle.get("current_feedback"),
        feedback_summary=bundle.get("feedback_summary"),
    )


@router.get("/feedback/stats", response_model=AIFeedbackResponse)
def feedback_stats(
    source: str = Query(..., min_length=1, max_length=32),
    source_id: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
) -> AIFeedbackResponse:
    normalized_source = source.strip().lower()
    normalized_source_id = (source_id or "").strip() or None
    counts = aggregate_feedback_counts(db, source=normalized_source, source_id=normalized_source_id)
    return AIFeedbackResponse(
        status="ok",
        source=normalized_source,
        source_id=normalized_source_id,
        helpful_votes=int(counts["helpful"]),
        not_helpful_votes=int(counts["not_helpful"]),
    )


@router.get("/feedback/analytics", response_model=AIRecommendationFeedbackSummaryWithBreakdown)
def feedback_analytics(
    source_surface: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
) -> AIRecommendationFeedbackSummaryWithBreakdown:
    payload = aggregate_agent_feedback_analytics(db, source_surface=source_surface)
    return AIRecommendationFeedbackSummaryWithBreakdown(**payload)


@router.get("/kb/search")
def kb_search(
    q: str = Query(..., min_length=1, max_length=2000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"query": "", "matches": []}

    try:
        matches = search_kb(db, query, top_k=5)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"semantic_kb_unavailable: {exc}") from exc

    return {
        "query": query,
        "matches": [
            {
                "score": round(float(match.get("score", 0.0)), 6),
                "jira_key": match.get("jira_key"),
                "snippet": _truncate_snippet(str(match.get("content") or "")),
                "metadata": match.get("metadata") or {},
            }
            for match in matches
        ],
    }


def _truncate_snippet(text: str, *, limit: int = 240) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


@router.get("/classification-logs")
def get_classification_logs(
    ticket_id: str | None = Query(default=None, description="Filter by ticket ID"),
    decision_source: str | None = Query(default=None, description="llm | semantic | fallback"),
    confidence_band: str | None = Query(default=None, description="high | medium | low"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Return paginated AI classification audit logs. Admin and agent only."""
    from app.models.ai_classification_log import AiClassificationLog
    from app.core.exceptions import InsufficientPermissionsError
    from sqlalchemy import select, func

    if current_user.role.value not in ("admin", "agent"):
        raise InsufficientPermissionsError("forbidden")

    stmt = select(AiClassificationLog)
    count_stmt = select(func.count()).select_from(AiClassificationLog)

    if ticket_id:
        stmt = stmt.where(AiClassificationLog.ticket_id == ticket_id.strip())
        count_stmt = count_stmt.where(AiClassificationLog.ticket_id == ticket_id.strip())
    if decision_source:
        stmt = stmt.where(AiClassificationLog.decision_source == decision_source.strip())
        count_stmt = count_stmt.where(AiClassificationLog.decision_source == decision_source.strip())
    if confidence_band:
        stmt = stmt.where(AiClassificationLog.confidence_band == confidence_band.strip())
        count_stmt = count_stmt.where(AiClassificationLog.confidence_band == confidence_band.strip())

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(AiClassificationLog.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": str(r.id),
                "ticket_id": r.ticket_id,
                "trigger": r.trigger,
                "title": r.title,
                "suggested_priority": r.suggested_priority,
                "suggested_category": r.suggested_category,
                "suggested_ticket_type": r.suggested_ticket_type,
                "confidence": r.confidence,
                "confidence_band": r.confidence_band,
                "decision_source": r.decision_source,
                "strong_match_count": r.strong_match_count,
                "recommendation_mode": r.recommendation_mode,
                "reasoning": r.reasoning,
                "model_version": r.model_version,
                "human_reviewed_at": r.human_reviewed_at.isoformat() if r.human_reviewed_at else None,
                "override_reason": r.override_reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/classification-logs/{log_id}/human-review")
def mark_classification_reviewed(
    log_id: str,
    override_reason: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """ISO 42001 human oversight — mark an AI classification decision as reviewed.

    Optionally supply an override_reason if the human disagrees with the AI decision.
    This creates a verifiable audit trail of human oversight over AI decisions,
    as required by ISO 42001 clause 6.1 (risk treatment) and clause 9.1 (monitoring).
    """
    import datetime as dt
    from app.models.ai_classification_log import AiClassificationLog
    from app.core.exceptions import InsufficientPermissionsError, NotFoundError

    if current_user.role.value not in ("admin", "agent"):
        raise InsufficientPermissionsError("forbidden")

    try:
        from uuid import UUID
        log_uuid = UUID(log_id)
    except ValueError:
        from app.core.exceptions import BadRequestError
        raise BadRequestError("invalid_log_id")

    log = db.get(AiClassificationLog, log_uuid)
    if not log:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("classification_log_not_found")

    log.human_reviewed_at = dt.datetime.now(dt.timezone.utc)
    log.override_reason = override_reason or None
    db.add(log)
    db.commit()
    db.refresh(log)

    return {
        "id": str(log.id),
        "human_reviewed_at": log.human_reviewed_at.isoformat(),
        "override_reason": log.override_reason,
        "reviewed_by": str(current_user.id),
    }
