"""Email dispatch and templates for notification delivery."""

from __future__ import annotations

from html import escape

from app.models.notification import Notification
from app.services.email import send_email


def _severity_color(severity: str) -> str:
    value = str(severity or "info").lower()
    if value == "critical":
        return "#dc2626"
    if value in {"high", "warning"}:
        return "#f97316"
    return "#2563eb"


def _build_notification_html(*, notification: Notification, frontend_base_url: str, mark_read_url: str) -> str:
    severity = str(notification.severity or "info").lower()
    color = _severity_color(severity)
    view_url = f"{frontend_base_url.rstrip('/')}{notification.link or '/notifications'}"
    title = escape(notification.title)
    body = escape(str(notification.body or ""))
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:20px;">
      <tr>
        <td align="center">
          <table role="presentation" width="620" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
            <tr><td style="background:#111827;color:#fff;padding:14px 18px;font-size:16px;font-weight:700;">Teamwil ITSM Notifications</td></tr>
            <tr><td style="height:6px;background:{color};"></td></tr>
            <tr>
              <td style="padding:18px;">
                <h2 style="margin:0 0 8px;font-size:18px;">{title}</h2>
                <p style="margin:0 0 14px;font-size:13px;color:#475569;">Severity: {escape(severity.upper())}</p>
                <p style="margin:0 0 18px;font-size:14px;line-height:1.6;">{body}</p>
                <p style="margin:0 0 10px;">
                  <a href="{escape(view_url, quote=True)}" style="display:inline-block;background:#0f766e;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:600;">View in Portal</a>
                </p>
                <p style="margin:0 0 16px;">
                  <a href="{escape(mark_read_url, quote=True)}" style="display:inline-block;background:#334155;color:#fff;text-decoration:none;padding:9px 13px;border-radius:8px;font-weight:600;">Mark as Read</a>
                </p>
                <p style="margin:0;font-size:12px;color:#64748b;">You're receiving this because your notification preferences allow this alert level.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _build_notification_text(*, notification: Notification, frontend_base_url: str) -> str:
    view_url = f"{frontend_base_url.rstrip('/')}{notification.link or '/notifications'}"
    return (
        f"[ITSM] {notification.title}\n\n"
        f"Severity: {notification.severity}\n"
        f"Source: {notification.source or 'system'}\n\n"
        f"{notification.body or ''}\n\n"
        f"View in portal: {view_url}\n"
    )


def _build_digest_html(*, items: list[Notification], frontend_base_url: str) -> str:
    lines = []
    for item in items:
        color = _severity_color(str(item.severity or "info"))
        url = f"{frontend_base_url.rstrip('/')}{item.link or '/notifications'}"
        lines.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid #e5e7eb;">'
            f'<div style="font-weight:600;color:#111827;">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:{color};margin-right:8px;"></span>'
            f'{escape(item.title)}</div>'
            f'<div style="font-size:12px;color:#475569;margin:4px 0 8px;">{escape(str(item.body or ""))}</div>'
            f'<a href="{escape(url, quote=True)}" style="font-size:12px;color:#0f766e;">Open</a></td></tr>'
        )
    view_all = f"{frontend_base_url.rstrip('/')}/notifications?unread=true"
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:20px;">
      <tr><td align="center">
        <table role="presentation" width="620" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
          <tr><td style="background:#111827;color:#fff;padding:14px 18px;font-size:16px;font-weight:700;">Teamwil ITSM Hourly Digest</td></tr>
          <tr><td style="padding:18px;">
            <p style="margin:0 0 12px;font-size:14px;">{len(items)} notifications require your attention.</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{''.join(lines)}</table>
            <p style="margin:14px 0 0;">
              <a href="{escape(view_all, quote=True)}" style="display:inline-block;background:#0f766e;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:600;">View All</a>
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""


def deliver_notification_email(
    *,
    user_email: str,
    notification: Notification | None,
    frontend_base_url: str,
    digest_items: list[Notification] | None = None,
) -> tuple[bool, str | None]:
    try:
        if digest_items:
            subject = f"[ITSM] {len(digest_items)} high-severity notifications"
            text = "\n".join([f"- {item.title}" for item in digest_items])
            html = _build_digest_html(items=digest_items, frontend_base_url=frontend_base_url)
            ok = send_email(user_email, subject, text, html_body=html)
            return ok, None if ok else "smtp_send_failed"

        if notification is None:
            return False, "missing_notification"
        severity = str(notification.severity or "info").upper()
        prefix = "[URGENT] " if str(notification.source or "").lower() == "sla" and str(notification.severity).lower() == "critical" else ""
        subject = f"{prefix}[ITSM-{severity}] {notification.title}"
        text = _build_notification_text(notification=notification, frontend_base_url=frontend_base_url)
        mark_read_url = f"{frontend_base_url.rstrip('/')}/notifications"
        html = _build_notification_html(notification=notification, frontend_base_url=frontend_base_url, mark_read_url=mark_read_url)
        ok = send_email(user_email, subject, text, html_body=html)
        return ok, None if ok else "smtp_send_failed"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

