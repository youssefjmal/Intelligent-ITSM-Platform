"""Admin translation endpoints for DB/Jira content."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.translation import (
    TranslationDatasetRequest,
    TranslationDatasetResponse,
    TranslationSuggestionRequest,
    TranslationSuggestionResponse,
)
from app.services.translations import build_translated_dataset, build_translated_suggestions

router = APIRouter(dependencies=[Depends(rate_limit("ai")), Depends(require_admin)])


@router.post("/dataset", response_model=TranslationDatasetResponse)
def translate_dataset(
    payload: TranslationDatasetRequest = Body(default=TranslationDatasetRequest()),
    db: Session = Depends(get_db),
) -> TranslationDatasetResponse:
    return build_translated_dataset(db, payload)


@router.post("/suggestions", response_model=TranslationSuggestionResponse)
def translate_suggestions(
    payload: TranslationSuggestionRequest,
) -> TranslationSuggestionResponse:
    return build_translated_suggestions(payload)

