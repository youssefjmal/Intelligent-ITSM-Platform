"""AI endpoints backed by service-layer orchestration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.ai import (
    AIFeedbackRequest,
    AIFeedbackResponse,
    ChatRequest,
    ChatResponse,
    ClassificationRequest,
    ClassificationResponse,
    SuggestRequest,
    SuggestResponse,
)
from app.services.ai.feedback import aggregate_feedback_counts, record_feedback
from app.services.embeddings import search_kb
from app.services.ai.orchestrator import handle_chat, handle_classify, handle_suggest

router = APIRouter(dependencies=[Depends(rate_limit("ai")), Depends(get_current_user)])


@router.post("/classify", response_model=ClassificationResponse)
def classify(payload: ClassificationRequest, db: Session = Depends(get_db)) -> ClassificationResponse:
    return handle_classify(payload, db)

 
@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ChatResponse:
    return handle_chat(payload, db, current_user)


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
