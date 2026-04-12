"""ISO 27001 A.12.4 — audit log retention enforcement.

Deletes security_events rows older than AUDIT_LOG_RETENTION_DAYS.
Called once at startup and can be triggered manually via the admin API.
Retention of 0 days means keep forever (purge is skipped).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security_event import SecurityEvent

logger = logging.getLogger(__name__)


def purge_old_audit_events(db: Session) -> int:
    """Delete security_events older than AUDIT_LOG_RETENTION_DAYS.

    Returns the number of rows deleted.
    """
    days = settings.AUDIT_LOG_RETENTION_DAYS
    if days <= 0:
        logger.debug("Audit purge skipped (AUDIT_LOG_RETENTION_DAYS=0 — keep forever)")
        return 0

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    deleted = (
        db.query(SecurityEvent)
        .filter(SecurityEvent.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info("Audit purge: removed %d security_events older than %d days (cutoff=%s)", deleted, days, cutoff.date())
    return deleted
