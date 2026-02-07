"""Recommendation endpoints backed by the database."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.schemas.recommendation import RecommendationOut
from app.services.recommendations import list_recommendations

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[RecommendationOut])
def get_recommendations(db: Session = Depends(get_db)) -> list[RecommendationOut]:
    return [RecommendationOut.model_validate(r) for r in list_recommendations(db)]
