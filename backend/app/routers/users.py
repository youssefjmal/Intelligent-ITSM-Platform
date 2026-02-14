"""Admin endpoints for user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.rate_limit import rate_limit
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.schemas.user import UserOut, UserRoleUpdate, UserSeniorityUpdate, UserSpecializationsUpdate
from app.services.users import delete_user, list_users, update_role, update_seniority, update_specializations

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(require_admin)])


@router.get("/", response_model=list[UserOut])
def get_users(db: Session = Depends(get_db)) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in list_users(db)]


@router.patch("/{user_id}/role", response_model=UserOut)
def set_role(user_id: str, payload: UserRoleUpdate, db: Session = Depends(get_db)) -> UserOut:
    user = update_role(db, user_id, payload.role)
    if not user:
        raise NotFoundError("user_not_found", details={"user_id": user_id})
    return UserOut.model_validate(user)


@router.patch("/{user_id}/seniority", response_model=UserOut)
def set_seniority(user_id: str, payload: UserSeniorityUpdate, db: Session = Depends(get_db)) -> UserOut:
    user = update_seniority(db, user_id, payload.seniority_level)
    if not user:
        raise NotFoundError("user_not_found", details={"user_id": user_id})
    return UserOut.model_validate(user)


@router.patch("/{user_id}/specializations", response_model=UserOut)
def set_specializations(
    user_id: str,
    payload: UserSpecializationsUpdate,
    db: Session = Depends(get_db),
) -> UserOut:
    user = update_specializations(db, user_id, payload.specializations)
    if not user:
        raise NotFoundError("user_not_found", details={"user_id": user_id})
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def remove_user(user_id: str, db: Session = Depends(get_db)) -> Response:
    if not delete_user(db, user_id):
        raise NotFoundError("user_not_found", details={"user_id": user_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
