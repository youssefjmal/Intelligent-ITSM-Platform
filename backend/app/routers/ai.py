"""AI endpoints backed by service-layer orchestration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.ai import ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse
from app.services.embeddings import search_kb
from app.services.ai.orchestrator import handle_chat, handle_classify

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
