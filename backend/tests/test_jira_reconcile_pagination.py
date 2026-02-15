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

    def rollback(self) -> None:
        return None


def test_reconcile_handles_pagination(monkeypatch) -> None:
    calls: list[int] = []
    upserted: list[str] = []

    class FakeJiraClient:
        def search_jql(self, *, jql: str, start_at: int, max_results: int, fields: str):  # noqa: ANN001
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

        def get_issue(self, issue_key: str, *, fields: str):  # noqa: ANN001
            return {
                "id": issue_key.replace("P-", ""),
                "key": issue_key,
                "fields": {
                    "summary": f"Issue {issue_key}",
                    "description": "desc",
                    "status": {"name": "Open", "statusCategory": {"key": "new"}},
                    "priority": {"name": "Medium"},
                    "issuetype": {"name": "Incident"},
                    "labels": [],
                    "components": [],
                    "assignee": {"displayName": "Agent"},
                    "reporter": {"displayName": "Reporter"},
                    "created": "2026-02-14T10:00:00.000+0000",
                    "updated": "2026-02-14T10:02:00.000+0000",
                    "comment": {"comments": [], "total": 0},
                },
            }

    def fake_upsert_bundle(_db, issue, jira_client):  # noqa: ANN001
        key = issue["key"]
        upserted.append(key)
        return service.SyncCounts(tickets_upserted=1)

    fake_state = SimpleNamespace(
        project_key="DEMO",
        last_synced_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
        last_error=None,
        updated_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
    )

    monkeypatch.setattr(service, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(service, "_upsert_issue_bundle", fake_upsert_bundle)
    monkeypatch.setattr(service, "_resolve_sync_state", lambda db, project_key: fake_state)

    result = service.reconcile(_FakeDb(), JiraReconcileRequest(project_key="DEMO"))

    assert result.issues_seen == 3
    assert result.tickets_upserted == 3
    assert result.comments_upserted == 0
    assert calls == [0, 2]
    assert upserted == ["P-1", "P-2", "P-3"]


def test_reconcile_detects_project_key_when_missing(monkeypatch) -> None:
    observed_jql: list[str] = []

    class FakeJiraClient:
        def search_updated_issues(self, *, since_iso: str, start_at: int, max_results: int, project_key: str | None):  # noqa: ANN001
            return {"issues": [{"key": "AUTO-1"}]}

        def search_jql(self, *, jql: str, start_at: int, max_results: int, fields: str):  # noqa: ANN001
            observed_jql.append(jql)
            return {"total": 0, "issues": []}

    def fake_resolve_state(_db, project_key):  # noqa: ANN001
        return SimpleNamespace(
            project_key=project_key,
            last_synced_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
            last_error=None,
            updated_at=dt.datetime(2026, 2, 14, 9, 0, tzinfo=dt.timezone.utc),
        )

    monkeypatch.setattr(service, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(service, "_resolve_sync_state", fake_resolve_state)
    monkeypatch.setattr(service.settings, "JIRA_PROJECT_KEY", "")

    result = service.reconcile(_FakeDb(), JiraReconcileRequest(project_key=None))

    assert result.project_key == "AUTO"
    assert observed_jql
    assert 'project = "AUTO"' in observed_jql[0]
