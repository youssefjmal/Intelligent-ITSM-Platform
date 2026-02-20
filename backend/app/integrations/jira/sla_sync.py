"""Jira SLA normalization and ticket sync helpers."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.jira.client import JiraClient
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

_FIRST_RESPONSE_HINTS = (
    "first response",
    "first-response",
    "firstresponse",
    "response",
)
_RESOLUTION_HINTS = (
    "time to resolution",
    "resolution",
    "resolve",
    "resolved",
)
_SPACE_RE = re.compile(r"\s+")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip().lower())


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text.replace("Z", "+00:00"), text]
    for candidate in candidates:
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _coerce_millis(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("millis", "ms", "value"):
            candidate = value.get(key)
            if candidate is not None:
                return _coerce_millis(candidate)
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _millis_to_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    return max(int(value // 60000), 0)


def _extract_sla_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for key in ("slas", "values", "slaValues"):
        raw = payload.get(key)
        if isinstance(raw, list):
            entries.extend([item for item in raw if isinstance(item, dict)])
        elif isinstance(raw, dict):
            values = raw.get("values")
            if isinstance(values, list):
                entries.extend([item for item in values if isinstance(item, dict)])

    nested_sla = payload.get("sla")
    if isinstance(nested_sla, dict):
        values = nested_sla.get("values")
        if isinstance(values, list):
            entries.extend([item for item in values if isinstance(item, dict)])

    if not entries and any(key in payload for key in ("name", "status", "dueDate", "remainingTime")):
        entries.append(payload)

    return entries


def _find_metric(
    entries: list[dict[str, Any]],
    *,
    hints: tuple[str, ...],
    exclude: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for metric in entries:
        if exclude is not None and metric is exclude:
            continue
        name = _normalize_text(metric.get("name") or metric.get("displayName") or metric.get("id"))
        if any(hint in name for hint in hints):
            return metric
    return None


def _select_metrics(entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not entries:
        return None, None

    first_metric = _find_metric(entries, hints=_FIRST_RESPONSE_HINTS)
    resolution_metric = _find_metric(entries, hints=_RESOLUTION_HINTS, exclude=first_metric)

    if first_metric is None:
        first_metric = entries[0]

    if resolution_metric is None:
        for metric in entries:
            if metric is not first_metric:
                resolution_metric = metric
                break

    return first_metric, resolution_metric


def _metric_state(status_text: str, *, breached: bool, completed: bool, paused: bool) -> str:
    normalized = _normalize_text(status_text)
    if breached or normalized in {"breached"}:
        return "breached"
    if paused or normalized in {"paused", "on hold", "on-hold"}:
        return "paused"
    if completed or normalized in {"completed", "done", "resolved"}:
        return "completed"
    if normalized in {"running", "in progress", "in-progress", "active", "ok"}:
        return "ok"
    return "unknown"


def _extract_metric_fields(metric: dict[str, Any]) -> dict[str, Any]:
    status_raw = str(
        metric.get("status")
        or ((metric.get("ongoingCycle") or {}).get("status") if isinstance(metric.get("ongoingCycle"), dict) else "")
        or ""
    ).strip()

    breached_value = _coerce_bool(metric.get("breached"))
    if breached_value is None and isinstance(metric.get("ongoingCycle"), dict):
        breached_value = _coerce_bool((metric.get("ongoingCycle") or {}).get("breached"))
    breached = bool(breached_value) if breached_value is not None else _normalize_text(status_raw) == "breached"

    completed_value = _coerce_bool(metric.get("completed"))
    completed = bool(completed_value) if completed_value is not None else False
    paused_value = _coerce_bool(metric.get("paused"))
    if paused_value is None and isinstance(metric.get("ongoingCycle"), dict):
        paused_value = _coerce_bool((metric.get("ongoingCycle") or {}).get("paused"))
    paused = bool(paused_value) if paused_value is not None else False

    due_at = _parse_datetime(
        metric.get("dueDate")
        or metric.get("targetDate")
        or (metric.get("ongoingCycle") or {}).get("breachTime")
        or (metric.get("goal") or {}).get("targetDate")
    )
    completed_at = _parse_datetime(metric.get("completedDate"))
    if completed_at is None and (completed or _normalize_text(status_raw) in {"completed", "done", "resolved"}):
        completed_at = _parse_datetime(metric.get("stopTime") or (metric.get("ongoingCycle") or {}).get("stopTime"))

    remaining_ms = _coerce_millis(metric.get("remainingTime"))
    if remaining_ms is None:
        remaining_ms = _coerce_millis((metric.get("ongoingCycle") or {}).get("remainingTime"))
    elapsed_ms = _coerce_millis(metric.get("elapsedTime"))
    if elapsed_ms is None:
        elapsed_ms = _coerce_millis((metric.get("ongoingCycle") or {}).get("elapsedTime"))

    return {
        "status": _metric_state(status_raw, breached=breached, completed=completed, paused=paused),
        "due_at": due_at,
        "breached": breached,
        "completed_at": completed_at,
        "remaining_minutes": _millis_to_minutes(remaining_ms),
        "elapsed_minutes": _millis_to_minutes(elapsed_ms),
    }


def parse_jira_sla(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Jira SLA payload to ticket-facing fields."""
    entries = _extract_sla_entries(payload)
    first_metric, resolution_metric = _select_metrics(entries)

    first_data = _extract_metric_fields(first_metric) if first_metric else {}
    resolution_data = _extract_metric_fields(resolution_metric) if resolution_metric else {}

    status = str(resolution_data.get("status") or first_data.get("status") or "unknown")
    if status == "unknown":
        statuses = [str(item.get("status") or "unknown") for item in (first_data, resolution_data) if item]
        if "breached" in statuses:
            status = "breached"
        elif "paused" in statuses:
            status = "paused"
        elif "completed" in statuses:
            status = "completed"
        elif "ok" in statuses:
            status = "ok"

    remaining_minutes = resolution_data.get("remaining_minutes")
    if remaining_minutes is None:
        remaining_minutes = first_data.get("remaining_minutes")
    elapsed_minutes = resolution_data.get("elapsed_minutes")
    if elapsed_minutes is None:
        elapsed_minutes = first_data.get("elapsed_minutes")

    return {
        "sla_status": status if status in {"ok", "paused", "breached", "completed", "unknown"} else "unknown",
        "sla_first_response_due_at": first_data.get("due_at"),
        "sla_resolution_due_at": resolution_data.get("due_at"),
        "sla_first_response_breached": bool(first_data.get("breached", False)),
        "sla_resolution_breached": bool(resolution_data.get("breached", False)),
        "sla_first_response_completed_at": first_data.get("completed_at"),
        "sla_resolution_completed_at": resolution_data.get("completed_at"),
        "sla_remaining_minutes": remaining_minutes,
        "sla_elapsed_minutes": elapsed_minutes,
    }


def _set_if_changed(ticket: Ticket, attr: str, value: Any) -> bool:
    if getattr(ticket, attr) == value:
        return False
    setattr(ticket, attr, value)
    return True


def sync_ticket_sla(
    db: Session,
    ticket: Ticket,
    jira_key: str,
    jira_client: JiraClient | None = None,
) -> bool:
    """Fetch Jira SLA details and update ticket SLA fields. Never raises."""
    key = (jira_key or "").strip()
    if not key:
        return False

    client = jira_client or JiraClient()
    try:
        payload = client.get_issue_sla(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira SLA fetch failed for %s: %s", key, exc)
        return False

    if not isinstance(payload, dict):
        payload = {}

    parsed = parse_jira_sla(payload) if payload else {
        "sla_status": "unknown",
        "sla_first_response_due_at": None,
        "sla_resolution_due_at": None,
        "sla_first_response_breached": False,
        "sla_resolution_breached": False,
        "sla_first_response_completed_at": None,
        "sla_resolution_completed_at": None,
        "sla_remaining_minutes": None,
        "sla_elapsed_minutes": None,
    }

    changed = False
    changed |= _set_if_changed(ticket, "jira_sla_payload", payload)
    changed |= _set_if_changed(ticket, "sla_status", parsed["sla_status"])
    changed |= _set_if_changed(ticket, "sla_first_response_due_at", parsed["sla_first_response_due_at"])
    changed |= _set_if_changed(ticket, "sla_resolution_due_at", parsed["sla_resolution_due_at"])
    changed |= _set_if_changed(ticket, "sla_first_response_breached", parsed["sla_first_response_breached"])
    changed |= _set_if_changed(ticket, "sla_resolution_breached", parsed["sla_resolution_breached"])
    changed |= _set_if_changed(ticket, "sla_first_response_completed_at", parsed["sla_first_response_completed_at"])
    changed |= _set_if_changed(ticket, "sla_resolution_completed_at", parsed["sla_resolution_completed_at"])
    changed |= _set_if_changed(ticket, "sla_remaining_minutes", parsed["sla_remaining_minutes"])
    changed |= _set_if_changed(ticket, "sla_elapsed_minutes", parsed["sla_elapsed_minutes"])
    ticket.sla_last_synced_at = _utcnow()

    db.add(ticket)
    db.flush()
    return changed
