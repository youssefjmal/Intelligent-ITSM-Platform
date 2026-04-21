"""Admin endpoints for the security_events audit log (ISO 27001 A.12.4)."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import require_admin
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.security_event import SecurityEvent
from app.services.audit_purge import purge_old_audit_events

router = APIRouter(
    dependencies=[Depends(rate_limit()), Depends(require_admin)],
)


@router.get("/monitoring/dashboards")
def monitoring_dashboards() -> dict[str, Any]:
    """Return configured external monitoring destinations for admin tools."""
    grafana_url = settings.GRAFANA_BASE_URL.strip() or None
    prometheus_url = settings.PROMETHEUS_BASE_URL.strip() or None
    return {
        "grafana_url": grafana_url,
        "prometheus_url": prometheus_url,
        "items": [
            {"name": "grafana", "label": "Grafana", "url": grafana_url},
            {"name": "prometheus", "label": "Prometheus", "url": prometheus_url},
        ],
    }


@router.get("/monitoring/grafana")
def redirect_to_grafana() -> RedirectResponse:
    """Admin-only redirect helper for Grafana."""
    target = settings.GRAFANA_BASE_URL.strip()
    if not target:
        target = "http://localhost:3003"
    return RedirectResponse(url=target, status_code=307)


@router.get("/security-events")
def list_security_events(
    event_type: str | None = Query(None, description="Filter by event_type (e.g. login_failed)"),
    user_id: str | None = Query(None, description="Filter by affected user UUID"),
    actor_id: str | None = Query(None, description="Filter by acting user UUID"),
    ip_address: str | None = Query(None, description="Filter by IP address"),
    from_date: dt.datetime | None = Query(None, description="ISO-8601 start timestamp (inclusive)"),
    to_date: dt.datetime | None = Query(None, description="ISO-8601 end timestamp (inclusive)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(SecurityEvent)
    count_stmt = select(func.count()).select_from(SecurityEvent)

    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type.strip())
        count_stmt = count_stmt.where(SecurityEvent.event_type == event_type.strip())
    if user_id:
        try:
            uid = UUID(user_id.strip())
            stmt = stmt.where(SecurityEvent.user_id == uid)
            count_stmt = count_stmt.where(SecurityEvent.user_id == uid)
        except ValueError:
            pass
    if actor_id:
        try:
            aid = UUID(actor_id.strip())
            stmt = stmt.where(SecurityEvent.actor_id == aid)
            count_stmt = count_stmt.where(SecurityEvent.actor_id == aid)
        except ValueError:
            pass
    if ip_address:
        stmt = stmt.where(SecurityEvent.ip_address == ip_address.strip())
        count_stmt = count_stmt.where(SecurityEvent.ip_address == ip_address.strip())
    if from_date:
        stmt = stmt.where(SecurityEvent.created_at >= from_date)
        count_stmt = count_stmt.where(SecurityEvent.created_at >= from_date)
    if to_date:
        stmt = stmt.where(SecurityEvent.created_at <= to_date)
        count_stmt = count_stmt.where(SecurityEvent.created_at <= to_date)

    total: int = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        stmt.order_by(SecurityEvent.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "user_id": str(row.user_id) if row.user_id else None,
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "metadata": row.event_metadata,
                "note": row.note,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.post("/audit-purge")
def trigger_audit_purge(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Manually enforce ISO 27001 audit log retention (deletes events older than AUDIT_LOG_RETENTION_DAYS).
    Runs automatically on app startup; use this endpoint to trigger it on-demand.
    """
    deleted = purge_old_audit_events(db)
    return {
        "deleted": deleted,
        "retention_days": settings.AUDIT_LOG_RETENTION_DAYS,
        "purge_cutoff": (
            (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=settings.AUDIT_LOG_RETENTION_DAYS)).isoformat()
            if settings.AUDIT_LOG_RETENTION_DAYS > 0 else None
        ),
    }


@router.get("/compliance-summary")
def compliance_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """ISO 27001 / ISO 42001 compliance overview — event counts, retention policy, data classification labels."""
    from app.models.ai_classification_log import AiClassificationLog

    total_events: int = db.execute(select(func.count()).select_from(SecurityEvent)).scalar_one()

    # Count security events by event_type for the last 30 days
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    sec_rows = db.execute(
        select(SecurityEvent.event_type, func.count().label("n"))
        .where(SecurityEvent.created_at >= since)
        .group_by(SecurityEvent.event_type)
        .order_by(func.count().desc())
    ).all()

    # ISO 42001 AI governance metrics
    total_ai_logs: int = db.execute(select(func.count()).select_from(AiClassificationLog)).scalar_one()
    reviewed_count: int = db.execute(
        select(func.count()).select_from(AiClassificationLog)
        .where(AiClassificationLog.human_reviewed_at.isnot(None))
    ).scalar_one()
    overridden_count: int = db.execute(
        select(func.count()).select_from(AiClassificationLog)
        .where(AiClassificationLog.override_reason.isnot(None))
    ).scalar_one()
    ai_source_rows = db.execute(
        select(AiClassificationLog.decision_source, func.count().label("n"))
        .group_by(AiClassificationLog.decision_source)
    ).all()
    ai_conf_rows = db.execute(
        select(AiClassificationLog.confidence_band, func.count().label("n"))
        .group_by(AiClassificationLog.confidence_band)
    ).all()

    review_rate = round(reviewed_count / total_ai_logs * 100, 1) if total_ai_logs else 0.0

    return {
        "iso_27001": {
            "audit_log_retention_days": settings.AUDIT_LOG_RETENTION_DAYS,
            "total_security_events": total_events,
            "events_last_30d": {r.event_type: r.n for r in sec_rows},
            "data_classification": {
                "ticket_content": settings.DATA_CLASS_TICKET_CONTENT,
                "user_pii": settings.DATA_CLASS_USER_PII,
                "audit_logs": settings.DATA_CLASS_AUDIT_LOGS,
                "ai_logs": settings.DATA_CLASS_AI_LOGS,
            },
            "controls_implemented": [
                "A.9 — Access control (RBAC, role-change audit)",
                "A.9.4 — Brute-force lockout (5 attempts / 15 min)",
                "A.10 — Cryptography (JWT HS256+, bcrypt passwords, algorithm allowlist)",
                "A.12.4 — Audit logging (security_events, ai_classification_logs)",
                "A.12.4 — Log retention enforcement (AUDIT_LOG_RETENTION_DAYS)",
                "A.13 — Network controls (CORS allowlist, TrustedHostMiddleware, rate limiting)",
                "A.14 — Secure development (SameSite=Strict cookies, CSP, HSTS in prod)",
                "A.16 — Incident indicators (suspicious_activity, rate_limit_breach events)",
            ],
        },
        "iso_42001": {
            "standard": "ISO/IEC 42001:2023 — AI Management System",
            "total_ai_classification_decisions": total_ai_logs,
            "human_reviewed": reviewed_count,
            "human_overridden": overridden_count,
            "human_review_rate_pct": review_rate,
            "decisions_by_source": {r.decision_source: r.n for r in ai_source_rows},
            "decisions_by_confidence": {(r.confidence_band or "unknown"): r.n for r in ai_conf_rows},
            "controls_implemented": [
                "Clause 6.1 — AI risk treatment: human_reviewed_at + override_reason on every decision",
                "Clause 8.4 — AI system documentation: AI_WORKFLOW_README.md + AUTONOMOUS_REVIEW_REPORT.md",
                "Clause 9.1 — Performance monitoring: classification confidence bands tracked",
                "Clause 9.1 — Human oversight endpoint: POST /api/ai/classification-logs/{id}/human-review",
                "Clause 10.1 — Continual improvement: feedback loop via ai_solution_feedback table",
                "Transparency: model_version stamped on every ai_classification_logs row",
            ],
        },
    }
