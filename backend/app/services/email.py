"""Service helpers for logging and composing system emails."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from html import escape

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_log import EmailLog
from app.models.enums import EmailKind

logger = logging.getLogger(__name__)


def _wrap_email_html(*, title: str, intro: str, content: str, footer: str) -> str:
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
  </head>
  <body style="margin:0;padding:0;background:#f3f6f8;font-family:Arial,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border-radius:14px;border:1px solid #e2e8f0;overflow:hidden;">
            <tr>
              <td style="padding:20px 24px;background:linear-gradient(90deg,#0f9d58,#f59e0b);color:#ffffff;">
                <h1 style="margin:0;font-size:20px;line-height:1.3;">{escape(title)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;">
                <p style="margin:0 0 14px;font-size:15px;line-height:1.6;">{escape(intro)}</p>
                {content}
              </td>
            </tr>
            <tr>
              <td style="padding:16px 24px;background:#f8fafc;border-top:1px solid #e2e8f0;">
                <p style="margin:0;font-size:12px;line-height:1.6;color:#475569;">{escape(footer)}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _cta_button(label: str, href: str) -> str:
    safe_label = escape(label)
    safe_href = escape(href, quote=True)
    return (
        '<p style="margin:20px 0;">'
        f'<a href="{safe_href}" '
        'style="display:inline-block;background:#0f9d58;color:#ffffff;text-decoration:none;'
        'padding:12px 18px;border-radius:8px;font-weight:600;font-size:14px;">'
        f"{safe_label}</a></p>"
    )


def build_verification_email(name: str, token: str, code: str) -> tuple[str, str, str]:
    link = f"{settings.FRONTEND_BASE_URL}/auth/verify?token={token}"
    subject = "Verification de votre compte Teamwil"
    body = (
        f"Bonjour {name},\n\n"
        "Merci de verifier votre compte pour activer votre acces.\n\n"
        f"Code de verification: {code}\n\n"
        f"Lien de verification: {link}\n\n"
        "Le code expire avec ce lien apres 24 heures.\n\n"
        "Si vous n'etes pas a l'origine de cette demande, ignorez cet email."
    )
    html_content = (
        f'<p style="margin:0 0 12px;font-size:14px;color:#334155;">Bonjour {escape(name)},</p>'
        '<p style="margin:0 0 16px;font-size:14px;color:#334155;line-height:1.6;">'
        "Utilisez ce code de verification pour activer votre compte :</p>"
        '<div style="margin:0 0 18px;padding:14px;border:1px dashed #16a34a;border-radius:10px;'
        'background:#f0fdf4;text-align:center;">'
        f'<span style="font-size:30px;letter-spacing:7px;font-weight:700;color:#166534;">{escape(code)}</span>'
        "</div>"
        '<p style="margin:0 0 8px;font-size:14px;color:#334155;">Vous pouvez aussi verifier via ce lien :</p>'
        f"{_cta_button('Verifier mon email', link)}"
        '<p style="margin:0;font-size:12px;color:#64748b;line-height:1.6;">'
        f"Si le bouton ne fonctionne pas, copiez ce lien :<br>{escape(link)}</p>"
    )
    html_body = _wrap_email_html(
        title="Teamwil - Verification email",
        intro="Verification requise avant la premiere connexion.",
        content=html_content,
        footer="Ce message a ete envoye automatiquement. Ne partagez jamais votre code.",
    )
    return subject, body, html_body


def build_welcome_email(name: str) -> tuple[str, str, str]:
    subject = "Bienvenue sur TeamWill ITSM"
    body = (
        f"Bonjour {name},\n\n"
        "Votre compte est maintenant actif.\n\n"
        "Un administrateur vous attribuera un role si necessaire.\n\n"
        f"Vous pouvez vous connecter au portail ITSM: {settings.FRONTEND_BASE_URL}/auth/login"
    )
    html_content = (
        f'<p style="margin:0 0 12px;font-size:14px;color:#334155;">Bonjour {escape(name)},</p>'
        '<p style="margin:0 0 14px;font-size:14px;color:#334155;line-height:1.6;">'
        "Votre compte est maintenant actif.</p>"
        '<p style="margin:0 0 14px;font-size:14px;color:#334155;line-height:1.6;">'
        "Un administrateur vous attribuera un role si necessaire.</p>"
        f"{_cta_button('Se connecter', f'{settings.FRONTEND_BASE_URL}/auth/login')}"
    )
    html_body = _wrap_email_html(
        title="Bienvenue sur Teamwil ITSM",
        intro="Votre adresse email a bien ete verifiee.",
        content=html_content,
        footer="Merci d'utiliser Teamwil.",
    )
    return subject, body, html_body


def build_password_reset_email(name: str, token: str) -> tuple[str, str, str]:
    link = f"{settings.FRONTEND_BASE_URL}/auth/reset-password?token={token}"
    subject = "Reinitialisation de votre mot de passe"
    body = (
        f"Bonjour {name},\n\n"
        "Nous avons recu une demande de reinitialisation de mot de passe.\n\n"
        f"Lien de reinitialisation: {link}\n\n"
        "Ce lien expire dans 2 heures.\n\n"
        "Si vous n'etes pas a l'origine de cette demande, vous pouvez ignorer cet email."
    )
    html_content = (
        f'<p style="margin:0 0 12px;font-size:14px;color:#334155;">Bonjour {escape(name)},</p>'
        '<p style="margin:0 0 14px;font-size:14px;color:#334155;line-height:1.6;">'
        "Nous avons recu une demande de reinitialisation de mot de passe.</p>"
        f"{_cta_button('Reinitialiser mon mot de passe', link)}"
        '<p style="margin:0;font-size:12px;color:#64748b;line-height:1.6;">'
        f"Ce lien expire dans 2 heures. Lien direct :<br>{escape(link)}</p>"
    )
    html_body = _wrap_email_html(
        title="Reinitialisation du mot de passe",
        intro="Action de securite pour votre compte Teamwil.",
        content=html_content,
        footer="Si vous n'etes pas a l'origine de cette demande, ignorez simplement cet email.",
    )
    return subject, body, html_body


def send_email(to: str, subject: str, body: str, *, html_body: str | None = None) -> bool:
    if not settings.SMTP_HOST:
        logger.info("SMTP not configured; skipping send to %s", to)
        return False
    if not settings.SMTP_FROM:
        logger.warning("SMTP_FROM not configured; skipping send to %s", to)
        return False

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if settings.SMTP_TLS:
                server.starttls()
                server.ehlo()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
        logger.info("Email sent: %s", to)
        return True
    except Exception:
        logger.exception("Email send failed: %s", to)
        return False


def log_email(
    db: Session,
    to: str,
    subject: str,
    body: str,
    kind: EmailKind,
    *,
    html_body: str | None = None,
) -> EmailLog:
    send_email(to, subject, body, html_body=html_body)
    record = EmailLog(to=to, subject=subject, body=body, kind=kind)
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("Email logged: %s (%s)", to, kind.value)
    return record
