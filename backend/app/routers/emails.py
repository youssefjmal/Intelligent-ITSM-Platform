"""Admin endpoints for email log inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.email_log import EmailLog
from app.schemas.email import EmailLogOut

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/", response_model=list[EmailLogOut])
def list_emails(db: Session = Depends(get_db)) -> list[EmailLogOut]:
    records = db.query(EmailLog).order_by(EmailLog.sent_at.desc()).all()
    return [EmailLogOut.model_validate(r) for r in records]
