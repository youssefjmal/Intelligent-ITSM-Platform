"""AI endpoints backed by service-layer orchestration."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.ai import ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse
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

