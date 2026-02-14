from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.integrations.jira import service
from app.integrations.jira.schemas import JiraReconcileRequest


class _FakeDb:
    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None


def test_reconcile_handles_pagination(monkeypatch) -> None:
    calls: list[int] = []
    upserted: list[str] = []

    class FakeJiraClient:
        def search_updated_issues(self, *, since_iso: str, start_at: int, max_results: int, project_key: str | None = None):  # noqa: ANN001
            calls.append(start_at)
            if start_at == 0:
                return {
                    "total": 3,
                    "issues": [
                        {"key": "P-1", "fields": {"updated": "2026-02-14T10:00:00.000+0000"}},
                        {"key": "P-2", "fields": {"updated": "2026-02-14T10:01:00.000+0000"}},
                    ],
                }
            if start_at == 2:
                return {
                    "total": 3,
                    "issues": [
                        {"key": "P-3", "fields": {"updated": "2026-02-14T10:02:00.000+0000"}},
                    ],
                }
            return {"total": 3, "issues": []}

    def fake_upsert(_db, payload):  # noqa: ANN001
        key = payload["issue"]["key"]
        upserted.append(key)
        return SimpleNamespace(created=True, updated=False, jira_key=key)

    fake_state = SimpleNamespace(
        project_key="DEMO",
        last_synced_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
        last_cursor=None,
        updated_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
    )

    monkeypatch.setattr(service, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(service, "upsert_from_payload", fake_upsert)
    monkeypatch.setattr(service, "_resolve_sync_state", lambda db, project_key: fake_state)

    result = service.reconcile(_FakeDb(), JiraReconcileRequest(project_key="DEMO"))

    assert result.fetched == 3
    assert result.created == 3
    assert result.updated == 0
    assert calls == [0, 2]
    assert upserted == ["P-1", "P-2", "P-3"]
