"""AI endpoints backed by local rule-based logic until Ollama is wired."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import TicketCategory, TicketPriority, UserRole
from app.schemas.ai import ChatRequest, ChatResponse, ClassificationRequest, ClassificationResponse, TicketDraft
from app.services.ai import build_chat_reply, classify_ticket
from app.services.tickets import compute_stats, list_tickets
from app.services.users import list_assignees

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/classify", response_model=ClassificationResponse)
def classify(payload: ClassificationRequest) -> ClassificationResponse:
    priority, category, recommendations = classify_ticket(payload.title, payload.description)
    return ClassificationResponse(priority=priority, category=category, recommendations=recommendations)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ChatResponse:
    tickets = list_tickets(db)
    stats = compute_stats(tickets)
    last_question = payload.messages[-1].content if payload.messages else ""
    top = [
        f"{t.id} - {t.title}"
        for t in tickets[:5]
    ]
    assignees = list_assignees(db)
    assignee_names = [u.name for u in assignees]
    reply, action, ticket_payload = build_chat_reply(
        last_question,
        stats,
        top,
        locale=payload.locale,
        assignees=assignee_names,
    )

    ticket: TicketDraft | None = None
    if action == "create_ticket" and isinstance(ticket_payload, dict):
        title = str(ticket_payload.get("title") or last_question or "New ticket")
        description = str(ticket_payload.get("description") or last_question or title)
        try:
            priority = TicketPriority(ticket_payload.get("priority"))
            category = TicketCategory(ticket_payload.get("category"))
        except Exception:
            priority, category, _ = classify_ticket(title, description)
        tags = ticket_payload.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        assignee = ticket_payload.get("assignee")
        if assignee and assignee_names and assignee not in assignee_names:
            assignee = None
        if not assignee:
            if getattr(current_user, "role", None) in {UserRole.admin, UserRole.agent}:
                assignee = current_user.name
            elif assignee_names:
                assignee = assignee_names[0]
        ticket = TicketDraft(
            title=title,
            description=description,
            priority=priority,
            category=category,
            tags=tags,
            assignee=assignee,
        )

    return ChatResponse(reply=reply, action=action, ticket=ticket)
