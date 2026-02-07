"""Service helpers for recommendation queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.recommendation import Recommendation


def list_recommendations(db: Session) -> list[Recommendation]:
    return db.query(Recommendation).order_by(Recommendation.created_at.desc()).all()
