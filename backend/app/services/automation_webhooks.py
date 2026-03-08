"""Best-effort outbound calls to n8n webhook automations."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.services.notifications_service import (
    create_notifications_for_users,
    resolve_problem_recipients,
    resolve_ticket_recipients,
)

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return str(settings.N8N_WEBHOOK_BASE_URL or "").strip().rstrip("/")


def _post(path: str, payload: dict[str, Any]) -> bool:
    base = _base_url()
    if not base:
        return False
    url = f"{base}/{path.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    secret = str(settings.AUTOMATION_SECRET or "").strip()
    if secret:
        headers["X-Automation-Secret"] = secret
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                logger.warning("n8n webhook failed: %s status=%s body=%s", url, response.status_code, response.text[:300])
                return False
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("n8n webhook call failed: %s (%s)", url, exc)
    return False


def _fallback_notify_critical_ticket(db: Session, *, ticket: Ticket, trace_id: str) -> None:
    recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
    if not recipients:
        return
    create_notifications_for_users(
        db,
        users=recipients,
        title=f"Critical ticket detected: {ticket.id}",
        body=ticket.title,
        severity="critical",
        link=f"/tickets/{ticket.id}",
        source="n8n",
        cooldown_minutes=30,
        metadata_json={"workflow_name": "backend_fallback_critical_ticket", "trace_id": trace_id},
    )
    db.commit()


def trigger_critical_ticket_detected(db: Session, ticket: Ticket) -> None:
    if str(ticket.priority.value).lower() != "critical":
        return
    trace_id = f"critical-{ticket.id}-{int(dt.datetime.now(dt.timezone.utc).timestamp())}"
    payload = {
        "ticket_id": ticket.id,
        "priority": ticket.priority.value,
        "trace_id": trace_id,
    }
    if not _post("critical-ticket-detected", payload):
        _fallback_notify_critical_ticket(db, ticket=ticket, trace_id=trace_id)


def _fallback_notify_problem(db: Session, *, problem: Problem, trace_id: str) -> None:
    recipients = resolve_problem_recipients(db, problem=problem, include_admins=True)
    if not recipients:
        return
    create_notifications_for_users(
        db,
        users=recipients,
        title=f"Problem detected: {problem.id}",
        body=problem.title,
        severity="critical",
        link=f"/problems/{problem.id}",
        source="n8n",
        cooldown_minutes=30,
        metadata_json={"workflow_name": "backend_fallback_problem_detected", "trace_id": trace_id},
    )
    db.commit()


def trigger_problem_detected(db: Session, problem: Problem) -> None:
    trace_id = f"problem-{problem.id}-{int(dt.datetime.now(dt.timezone.utc).timestamp())}"
    payload = {
        "problem_id": problem.id,
        "title": problem.title,
        "severity": "critical",
        "affected_tickets_count": int(problem.active_count or 0),
        "trace_id": trace_id,
    }
    if not _post("problem-detected", payload):
        _fallback_notify_problem(db, problem=problem, trace_id=trace_id)
