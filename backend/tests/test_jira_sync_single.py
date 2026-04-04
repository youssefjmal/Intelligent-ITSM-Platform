"""Tests for the single-ticket sync endpoint and auto-reconcile silent-failure fix."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.integrations.jira.auto_reconcile import _run_once
from app.integrations.jira.service import SyncCounts
from app.routers.integrations_jira import jira_sync_single


# ---------------------------------------------------------------------------
# auto_reconcile — credentials-not-configured warning must be at WARNING level
# ---------------------------------------------------------------------------


def test_auto_reconcile_logs_warning_when_jira_not_ready(monkeypatch, caplog) -> None:
    """_run_once() must emit a WARNING (not just DEBUG) when credentials are missing
    so the problem is visible with the default LOG_LEVEL=INFO."""
    monkeypatch.setattr("app.integrations.jira.auto_reconcile._jira_ready", lambda: False)
    with caplog.at_level(logging.WARNING, logger="app.integrations.jira.auto_reconcile"):
        _run_once()
    assert any("credentials" in record.message.lower() for record in caplog.records), (
        "Expected a WARNING mentioning 'credentials' when Jira is not ready; "
        f"got records: {[r.message for r in caplog.records]}"
    )
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, "Expected at least one WARNING-level log record"


# ---------------------------------------------------------------------------
# jira_sync_single endpoint — calls sync_issue_by_key and returns counts
# ---------------------------------------------------------------------------


def test_jira_sync_single_returns_counts_on_success(monkeypatch) -> None:
    counts = SyncCounts(tickets_upserted=1, comments_upserted=2, comments_updated=0, skipped=0)
    monkeypatch.setattr(
        "app.routers.integrations_jira.sync_issue_by_key",
        lambda db, key: counts,
    )
    result = jira_sync_single(
        issue_key="HP-99",
        db=object(),
        current_user=SimpleNamespace(id="u-1"),
        _require_admin=None,
    )
    assert result["issue_key"] == "HP-99"
    assert result["tickets_upserted"] == 1
    assert result["comments_upserted"] == 2
    assert result["skipped"] == 0


def test_jira_sync_single_normalises_issue_key_to_uppercase(monkeypatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "app.routers.integrations_jira.sync_issue_by_key",
        lambda db, key: captured.append(key) or SyncCounts(),
    )
    jira_sync_single(
        issue_key="hp-42",
        db=object(),
        current_user=SimpleNamespace(id="u-1"),
        _require_admin=None,
    )
    assert captured == ["HP-42"]


def test_jira_sync_single_raises_bad_request_on_empty_key(monkeypatch) -> None:
    from app.core.exceptions import BadRequestError
    with pytest.raises(BadRequestError):
        jira_sync_single(
            issue_key="   ",
            db=object(),
            current_user=SimpleNamespace(id="u-1"),
            _require_admin=None,
        )


def test_jira_sync_single_propagates_value_error_as_bad_request(monkeypatch) -> None:
    from app.core.exceptions import BadRequestError
    monkeypatch.setattr(
        "app.routers.integrations_jira.sync_issue_by_key",
        lambda db, key: (_ for _ in ()).throw(ValueError("issue_fetch_failed")),
    )
    with pytest.raises(BadRequestError):
        jira_sync_single(
            issue_key="HP-404",
            db=object(),
            current_user=SimpleNamespace(id="u-1"),
            _require_admin=None,
        )
