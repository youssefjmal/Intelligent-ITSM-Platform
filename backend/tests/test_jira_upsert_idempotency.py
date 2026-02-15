from __future__ import annotations

from types import SimpleNamespace

from app.integrations.jira import service


class _FakeDb:
    def flush(self) -> None:
        return None


def test_upsert_bundle_same_payload_twice_is_idempotent(monkeypatch) -> None:
    seen_tickets: set[str] = set()
    seen_comments: set[tuple[str, str]] = set()

    def fake_upsert_ticket(db, issue):  # noqa: ANN001
        key = str(issue.get("key") or "")
        upserted = key not in seen_tickets
        seen_tickets.add(key)
        ticket = SimpleNamespace(id="JSM-TEST-2")
        return ticket, upserted

    def fake_all_issue_comments(issue, jira_client):  # noqa: ANN001
        return (((issue.get("fields") or {}).get("comment") or {}).get("comments") or [])

    def fake_upsert_comment(db, ticket, comment_payload):  # noqa: ANN001
        comment_id = str((comment_payload or {}).get("id") or "")
        key = (ticket.id, comment_id)
        if key in seen_comments:
            return "skipped"
        seen_comments.add(key)
        return "upserted"

    monkeypatch.setattr(service, "_upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(service, "_all_issue_comments", fake_all_issue_comments)
    monkeypatch.setattr(service, "_upsert_comment", fake_upsert_comment)

    issue = {
        "key": "TEST-2",
        "fields": {
            "summary": "Idempotent issue",
            "description": "desc",
            "status": {"name": "Open", "statusCategory": {"key": "new"}},
            "priority": {"name": "Medium"},
            "issuetype": {"name": "Incident"},
            "labels": [],
            "assignee": {"displayName": "A"},
            "reporter": {"displayName": "R"},
            "created": "2026-02-14T10:00:00.000+0000",
            "updated": "2026-02-14T10:00:00.000+0000",
            "comment": {
                "comments": [
                    {
                        "id": "101",
                        "body": "same body",
                        "author": {"displayName": "A"},
                        "created": "2026-02-14T10:01:00.000+0000",
                        "updated": "2026-02-14T10:01:00.000+0000",
                    }
                ]
            },
        },
    }

    result1 = service._upsert_issue_bundle(_FakeDb(), issue, jira_client=SimpleNamespace())
    result2 = service._upsert_issue_bundle(_FakeDb(), issue, jira_client=SimpleNamespace())

    assert result1.tickets_upserted == 1
    assert result2.tickets_upserted == 0
    assert len(seen_tickets) == 1
    assert len(seen_comments) == 1
