"""Row filtering helpers for Jira KB ranking."""

from __future__ import annotations

from typing import Any


def _normalize_filter_values(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            values.extend(_normalize_filter_values(item))
        return values
    value = str(raw).strip().lower()
    return [value] if value else []


def _csv_values(text: str) -> list[str]:
    return [part.strip().lower() for part in (text or "").split(",") if part.strip()]


def _matches_values(candidates: list[str], expected_values: list[str]) -> bool:
    if not expected_values:
        return True
    cleaned_candidates = [candidate for candidate in candidates if candidate]
    if not cleaned_candidates:
        return False
    for expected in expected_values:
        for candidate in cleaned_candidates:
            if expected in candidate or candidate in expected:
                return True
    return False


def _passes_filters(row: dict[str, str], filters: dict | None) -> bool:
    if not filters:
        return True

    issuetype = str(row.get("issuetype") or "").strip().lower()
    labels = _csv_values(str(row.get("labels") or ""))
    components = _csv_values(str(row.get("components") or ""))
    priority = str(row.get("priority") or "").strip().lower()
    status = str(row.get("status") or "").strip().lower()

    category_values = _normalize_filter_values(filters.get("category"))
    if category_values and not _matches_values([issuetype, *labels], category_values):
        return False

    service_values = _normalize_filter_values(filters.get("service"))
    if service_values and not _matches_values([issuetype, *labels], service_values):
        return False

    component_values = _normalize_filter_values(filters.get("component"))
    if component_values and not _matches_values(components, component_values):
        return False

    priority_values = _normalize_filter_values(filters.get("priority"))
    if priority_values and not _matches_values([priority], priority_values):
        return False

    status_values = _normalize_filter_values(filters.get("status"))
    if status_values and not _matches_values([status], status_values):
        return False

    return True
