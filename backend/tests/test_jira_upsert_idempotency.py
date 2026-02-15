from __future__ import annotations

from types import SimpleNamespace

from app.integrations.jira import service
from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.services import problems as problems_service


class _FakeDb:
    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def flush(self) -> None:
        return None


def test_upsert_bundle_same_payload_twice_is_idempotent(monkeypatch) -> None:
    seen_tickets: set[str] = set()
    seen_comments: set[tuple[str, str]] = set()

    def fake_upsert_ticket(db, issue):  # noqa: ANN001
        key = str(issue.get("key") or "")
        upserted = key not in seen_tickets
        seen_tickets.add(key)
        ticket = SimpleNamespace(
            id="JSM-TEST-2",
            reporter="Reporter",
            status=service.TicketStatus.open,
            first_action_at=None,
            jira_updated_at=None,
            resolved_at=None,
            problem_id=None,
        )
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
    monkeypatch.setattr(problems_service, "link_ticket_to_problem", lambda _db, _ticket: None)

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


def test_extract_local_ticket_id_from_summary() -> None:
    issue = {
        "key": "HP-200",
        "fields": {
            "summary": "[TW-2020] VPN timeout issue",
            "labels": [],
        },
    }
    assert service._extract_local_ticket_id(issue) == "TW-2020"


def test_extract_local_ticket_id_from_seed_label() -> None:
    issue = {
        "key": "HP-201",
        "fields": {
            "summary": "Regular summary",
            "labels": ["source_local_itsm", "twseed_tw_3030"],
        },
    }
    assert service._extract_local_ticket_id(issue) == "TW-3030"


def test_extract_local_ticket_id_from_local_label() -> None:
    issue = {
        "key": "HP-202",
        "fields": {
            "summary": "Regular summary",
            "labels": ["local_tw_4040"],
        },
    }
    assert service._extract_local_ticket_id(issue) == "TW-4040"


def test_upsert_ticket_applies_ai_category_for_unknown_jsm_issue_type(monkeypatch) -> None:
    monkeypatch.setattr(service, "_find_ticket_for_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        service,
        "classify_ticket",
        lambda title, description: (TicketPriority.high, TicketCategory.network, ["rec"]),
    )

    issue = {
        "id": "5001",
        "key": "HP-5001",
        "fields": {
            "summary": "VPN timeout incident",
            "description": "Users cannot connect to VPN.",
            "status": {"name": "Open", "statusCategory": {"key": "new"}},
            "priority": {"name": "Medium"},
            "issuetype": {"name": "Email Request"},
            "labels": [],
            "components": [],
            "assignee": {"displayName": "Agent"},
            "reporter": {"displayName": "Reporter"},
            "created": "2026-02-14T10:00:00.000+0000",
            "updated": "2026-02-14T10:05:00.000+0000",
            "comment": {"comments": [], "total": 0},
        },
    }

    ticket, upserted = service._upsert_ticket(_FakeDb(), issue)

    assert upserted is True
    assert ticket.status == TicketStatus.open
    assert ticket.category == TicketCategory.network
    assert ticket.priority == TicketPriority.medium
    assert ticket.predicted_category == TicketCategory.network
    assert ticket.predicted_priority == TicketPriority.high
