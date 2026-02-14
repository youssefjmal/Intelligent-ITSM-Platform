from __future__ import annotations

from app.integrations.jira.mapper import map_issue, map_priority, map_status
from app.models.enums import TicketPriority, TicketStatus


def _issue_payload(*, status_name: str, priority_name: str) -> dict:
    return {
        "key": "TEST-1",
        "fields": {
            "summary": "Sample issue",
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "desc"}]}]},
            "status": {"name": status_name, "statusCategory": {"key": "new"}},
            "priority": {"name": priority_name},
            "issuetype": {"name": "Incident"},
            "labels": ["a", "b"],
            "assignee": {"displayName": "Agent"},
            "reporter": {"displayName": "Reporter"},
            "created": "2026-02-14T10:00:00.000+0000",
            "updated": "2026-02-14T11:00:00.000+0000",
        },
    }


def test_status_priority_mapping_known_values() -> None:
    issue = _issue_payload(status_name="In Progress", priority_name="High")
    mapped = map_issue(issue)
    assert mapped.status == TicketStatus.in_progress
    assert mapped.priority == TicketPriority.high


def test_status_priority_mapping_unknown_defaults() -> None:
    fields = {"status": {"name": "SomethingElse", "statusCategory": {"key": ""}}, "priority": {"name": "UnknownPriority"}}
    assert map_status(fields) == TicketStatus.open
    assert map_priority(fields) == TicketPriority.medium
