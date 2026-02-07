"""AI endpoints backed by local rule-based logic until Ollama is wired."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.schemas.ai import ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse
from app.services.ai import build_chat_reply, classify_ticket
from app.services.tickets import compute_stats, list_tickets

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/classify", response_model=ClassificationResponse)
def classify(payload: ClassificationRequest) -> ClassificationResponse:
    priority, category, recommendations = classify_ticket(payload.title, payload.description)
    return ClassificationResponse(priority=priority, category=category, recommendations=recommendations)


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    tickets = list_tickets(db)
    stats = compute_stats(tickets)
    last_question = payload.messages[-1].content if payload.messages else ""
    top = [
        f"{t.id} - {t.title}"
        for t in tickets[:5]
    ]
    reply = build_chat_reply(last_question, stats, top)
    return ChatResponse(reply=reply)
