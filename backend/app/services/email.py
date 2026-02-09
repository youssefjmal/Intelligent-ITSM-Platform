"""Service helpers for logging and composing system emails."""

from __future__ import annotations

from sqlalchemy.orm import Session
import logging

from app.core.config import settings
from app.models.email_log import EmailLog
from app.models.enums import EmailKind

logger = logging.getLogger(__name__)


def build_verification_email(name: str, token: str) -> tuple[str, str]:
    link = f"{settings.FRONTEND_BASE_URL}/auth/verify?token={token}"
    subject = "Verification de votre compte"
    body = (
        f"Bonjour {name},\n\n"
        "Merci de verifier votre compte pour activer votre acces.\n\n"
        f"Lien de verification: {link}\n\n"
        "Si vous n'etes pas a l'origine de cette demande, ignorez cet email."
    )
    return subject, body


def build_welcome_email(name: str, role: str) -> tuple[str, str]:
    subject = "Bienvenue sur TeamWill ITSM"
    body = (
        f"Bonjour {name},\n\n"
        "Votre compte est maintenant actif.\n\n"
        f"Role: {role}\n\n"
        "Vous pouvez vous connecter au portail ITSM."
    )
    return subject, body


def log_email(db: Session, to: str, subject: str, body: str, kind: EmailKind) -> EmailLog:
    record = EmailLog(to=to, subject=subject, body=body, kind=kind)
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("Email logged: %s (%s)", to, kind.value)
    return record
