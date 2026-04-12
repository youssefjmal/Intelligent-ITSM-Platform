"""SecurityEvent model — immutable audit trail for security-relevant actions.

Every row is append-only: never update or delete rows from this table.
The `metadata` JSON column holds arbitrary extra context (ticket_id, role
changed to, etc.) without requiring schema migrations for each event type.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # What happened — use the constants below for consistency
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Who was affected (the account the event is about)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Who triggered the event (same as user_id for self-actions; admin id for role changes)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Network context
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max = 45 chars
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Free-form JSON for event-specific payload (role_from/to, lockout duration, etc.)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Human-readable note (optional)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


# ── event type constants ──────────────────────────────────────────────────────
# Import these wherever you call log_security_event() to avoid typos.
# All constants below are valid values for the event_type column.

# Authentication lifecycle
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED = "login_failed"
LOGIN_BLOCKED = "login_blocked"       # attempt while account is locked
ACCOUNT_LOCKED = "account_locked"     # lockout threshold reached
ACCOUNT_UNLOCKED = "account_unlocked" # lock expired / admin cleared it
LOGOUT = "logout"
TOKEN_REFRESHED = "token_refreshed"

# Credential management
PASSWORD_RESET_REQUESTED = "password_reset_requested"
PASSWORD_RESET_SUCCESS = "password_reset_success"

# Access control (ISO 27001 A.9)
ROLE_CHANGED = "role_changed"
USER_CREATED = "user_created"
USER_DELETED = "user_deleted"

# Data operations (ISO 27001 A.12 — logging of privileged operations)
DATA_EXPORT = "data_export"           # user triggered a bulk export (SLA CSV, etc.)
ADMIN_DATA_ACCESS = "admin_data_access"  # admin read sensitive records

# Threat indicators (ISO 27001 A.16 — incident management)
SUSPICIOUS_ACTIVITY = "suspicious_activity"  # anomaly flagged by a monitor
RATE_LIMIT_BREACH = "rate_limit_breach"      # caller exceeded rate limits repeatedly
