"""Authentication endpoints (register, login, verify, logout)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.enums import EmailKind
from app.models.user import User
from app.schemas.auth import RegisterResponse, ResendVerificationRequest, VerificationRequest, VerificationResponse
from app.schemas.user import UserCreate, UserLogin, UserOut
from app.services.auth import authenticate_user, create_user, create_verification_token, verify_email_token
from app.services.email import build_verification_email, build_welcome_email, log_email
from app.core.deps import get_current_user

router = APIRouter()


@router.post("/register", response_model=RegisterResponse)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> RegisterResponse:
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="email_exists")

    user = create_user(db, payload)
    token = create_verification_token(db, user)

    subject, body = build_verification_email(user.name, token.token)
    log_email(db, user.email, subject, body, EmailKind.verification)

    verification_token = token.token if settings.ENV == "development" else None
    return RegisterResponse(message="verification_sent", verification_token=verification_token)


@router.post("/login", response_model=UserOut)
def login_user(payload: UserLogin, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email_not_verified")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    response.set_cookie(
        settings.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.ENV != "development",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return UserOut.model_validate(user)


@router.post("/logout")
def logout_user(response: Response) -> dict:
    response.delete_cookie(settings.COOKIE_NAME)
    return {"message": "logged_out"}


@router.get("/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/verify", response_model=VerificationResponse)
def verify_email(payload: VerificationRequest, db: Session = Depends(get_db)) -> VerificationResponse:
    user = verify_email_token(db, payload.token)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_or_expired_token")

    subject, body = build_welcome_email(user.name, user.role.value)
    log_email(db, user.email, subject, body, EmailKind.welcome)

    return VerificationResponse(message="email_verified")


@router.post("/resend", response_model=RegisterResponse)
def resend_verification(payload: ResendVerificationRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
    if user.is_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="already_verified")

    token = create_verification_token(db, user)
    subject, body = build_verification_email(user.name, token.token)
    log_email(db, user.email, subject, body, EmailKind.verification)

    verification_token = token.token if settings.ENV == "development" else None
    return RegisterResponse(message="verification_sent", verification_token=verification_token)
