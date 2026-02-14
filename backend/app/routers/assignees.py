"""Endpoint for listing assignable users for ticket creation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.user import UserAssigneeOut
from app.services.users import list_assignees

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])


@router.get("/users/assignees", response_model=list[UserAssigneeOut])
def get_assignees(db: Session = Depends(get_db)) -> list[UserAssigneeOut]:
    return [UserAssigneeOut.model_validate(u) for u in list_assignees(db)]
