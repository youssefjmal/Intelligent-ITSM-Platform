from __future__ import annotations

from types import SimpleNamespace

from app.integrations.jira import service


class _FakeDb:
    def commit(self) -> None:
        return None


def test_upsert_same_payload_twice_is_idempotent(monkeypatch) -> None:
    seen_tickets: set[str] = set()
    seen_comments: set[tuple[str, str]] = set()

    def fake_upsert_ticket(db, mapped):  # noqa: ANN001
        created = mapped.external_id not in seen_tickets
        if created:
            seen_tickets.add(mapped.external_id)
        ticket = SimpleNamespace(id="JSM-TEST-2")
        return ticket, created, False if not created else False

    def fake_upsert_comment(db, ticket, mapped_comment):  # noqa: ANN001
        seen_comments.add((ticket.id, mapped_comment.external_comment_id))

    monkeypatch.setattr(service, "_upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(service, "_upsert_comment", fake_upsert_comment)

    payload = {
        "issue": {
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
    }

    result1 = service.upsert_from_payload(_FakeDb(), payload)
    result2 = service.upsert_from_payload(_FakeDb(), payload)

    assert result1.created is True
    assert result2.created is False
    assert len(seen_tickets) == 1
    assert len(seen_comments) == 1
