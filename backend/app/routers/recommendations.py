"""Recommendation endpoints backed by the database."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.user import User
from app.schemas.recommendation import RecommendationOut
from app.services.recommendations import list_recommendations
from app.services.tickets import list_tickets_for_user

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])


@router.get("/", response_model=list[RecommendationOut])
def get_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecommendationOut]:
    records = list_recommendations(db)
    visible_ticket_ids = {ticket.id for ticket in list_tickets_for_user(db, current_user)}
    scoped = [
        record
        for record in records
        if not record.related_tickets
        or any(ticket_id in visible_ticket_ids for ticket_id in record.related_tickets)
    ]
    return [RecommendationOut.model_validate(r) for r in scoped]
