from __future__ import annotations

import datetime as dt

from app.integrations.jira.outbound import (
    _find_best_account_id,
    _format_comment_text_for_jira,
    _issue_update_payload,
    _labels,
    _select_issue_type_id,
    _select_request_type,
    _summary_title,
)
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.models.ticket import Ticket


def test_summary_title_strips_local_ticket_prefixes() -> None:
    ticket = Ticket(
        id="TW-1008",
        title="[TW-1008] [TW-1008] Mise a jour du framework Angular vers v19",
        description="desc",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        assignee="Agent",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    assert _summary_title(ticket) == "Mise a jour du framework Angular vers v19"


def test_summary_title_collapses_duplicate_legacy_prefixes() -> None:
    ticket = Ticket(
        id="TW-1031",
        title="[JSM-HP-36] [JSM-HP-36] [TW-1031] Troubleshooting AWS Clustering Issue",
        description="desc",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        assignee="Agent",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    assert _summary_title(ticket) == "[JSM-HP-36] [TW-1031] Troubleshooting AWS Clustering Issue"


def test_summary_title_strips_matching_ticket_id_prefix_once() -> None:
    ticket = Ticket(
        id="JSM-HP-36",
        title="[JSM-HP-36] [TW-1031] Troubleshooting AWS Clustering Issue",
        description="desc",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        assignee="Agent",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    assert _summary_title(ticket) == "[TW-1031] Troubleshooting AWS Clustering Issue"


def test_select_issue_type_prefers_service_request_type_by_default() -> None:
    issue_types = [
        {"id": "10004", "name": "Task"},
        {"id": "10002", "name": "[System] Service request"},
        {"id": "10001", "name": "[System] Incident"},
    ]

    assert _select_issue_type_id(issue_types) == "10002"


def test_select_issue_type_prefers_incident_type_for_incident_ticket() -> None:
    issue_types = [
        {"id": "10004", "name": "Task"},
        {"id": "10002", "name": "[System] Service request"},
        {"id": "10001", "name": "[System] Incident"},
    ]

    assert _select_issue_type_id(issue_types, ticket_type=TicketType.incident) == "10001"


def test_select_request_type_falls_back_to_existing_emailed_request() -> None:
    ticket = Ticket(
        id="TW-1008",
        title="Generic imported ticket",
        description="desc",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.service_request,
        assignee="Agent",
        reporter="Reporter",
        tags=[],
        source="local",
    )
    request_types = [
        {"id": "6", "name": "Get IT help"},
        {"id": "13", "name": "Emailed request"},
    ]

    selected = _select_request_type(request_types, ticket)

    assert selected is not None
    assert selected["id"] == "13"


def test_select_request_type_prefers_incident_request_type_for_incidents() -> None:
    ticket = Ticket(
        id="TW-1099",
        title="VPN outage",
        description="Users cannot connect to VPN.",
        status=TicketStatus.open,
        priority=TicketPriority.high,
        ticket_type=TicketType.incident,
        category=TicketCategory.network,
        assignee="Agent",
        reporter="Reporter",
        tags=[],
        source="local",
    )
    request_types = [
        {"id": "13", "name": "Emailed request", "issueTypeId": "10002"},
        {"id": "7", "name": "Report a system problem", "issueTypeId": "10001"},
    ]

    selected = _select_request_type(request_types, ticket)

    assert selected is not None
    assert selected["id"] == "7"


def test_labels_preserve_category_and_local_assignee() -> None:
    ticket = Ticket(
        id="TW-1101",
        title="Printer replacement needed",
        description="desc",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.hardware,
        assignee="Karim Benali",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    labels = _labels(ticket)

    assert "category_hardware" in labels
    assert "local_assignee_karim_benali" in labels
    assert "local_reporter_reporter" in labels


def test_comment_text_prefixes_original_author_when_jira_actor_differs() -> None:
    rendered = _format_comment_text_for_jira(
        "Need more logs from the firewall.",
        author_name="Amina Rafi",
        jira_actor_name="Youssef Jmel",
    )

    assert rendered.startswith("[Platform author: Amina Rafi]")
    assert rendered.endswith("Need more logs from the firewall.")


def test_comment_text_skips_prefix_for_same_author() -> None:
    rendered = _format_comment_text_for_jira(
        "Shared from Jira operator.",
        author_name="Youssef Jmel",
        jira_actor_name="Youssef Jmel",
    )

    assert rendered == "Shared from Jira operator."


def test_issue_update_payload_sets_managed_category_component() -> None:
    class DummyClient:
        def get_project_components(self, project_key: str) -> list[dict]:
            assert project_key == "TEAMWILL"
            return [{"id": "10040", "name": "Network"}]

    ticket = Ticket(
        id="TW-1201",
        title="VPN latency spike",
        description="Users are seeing packet loss over VPN.",
        status=TicketStatus.open,
        priority=TicketPriority.high,
        ticket_type=TicketType.incident,
        category=TicketCategory.network,
        assignee="Karim Benali",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    payload = _issue_update_payload(ticket, client=DummyClient(), project_key="TEAMWILL")

    assert payload["components"] == [{"id": "10040"}]


def test_issue_update_payload_sets_due_date_for_jira() -> None:
    ticket = Ticket(
        id="TW-1201",
        title="VPN latency spike",
        description="Users are seeing packet loss over VPN.",
        status=TicketStatus.open,
        priority=TicketPriority.high,
        ticket_type=TicketType.incident,
        category=TicketCategory.network,
        assignee="Karim Benali",
        reporter="Reporter",
        tags=[],
        source="local",
        due_at=dt.datetime(2026, 3, 20, 15, 30, tzinfo=dt.timezone.utc),
    )

    payload = _issue_update_payload(ticket)

    assert payload["duedate"] == "2026-03-20"


def test_issue_update_payload_creates_missing_category_component() -> None:
    created: dict[str, str] = {}

    class DummyClient:
        def get_project_components(self, project_key: str) -> list[dict]:
            assert project_key == "TEAMWILL"
            return []

        def create_project_component(self, *, project_key: str, name: str, description: str | None = None) -> dict:
            created["project_key"] = project_key
            created["name"] = name
            created["description"] = description or ""
            return {"id": "10041", "name": name}

    ticket = Ticket(
        id="TW-1202",
        title="Mailbox setup request",
        description="Create a mailbox for a new employee.",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        ticket_type=TicketType.service_request,
        category=TicketCategory.email,
        assignee="Amina Rafi",
        reporter="Reporter",
        tags=[],
        source="local",
    )

    payload = _issue_update_payload(ticket, client=DummyClient(), project_key="TEAMWILL")

    assert created["project_key"] == "TEAMWILL"
    assert created["name"] == "Email"
    assert "category sync" in created["description"]
    assert payload["components"] == [{"id": "10041"}]


def test_find_best_account_id_skips_customer_accounts_for_native_assignment() -> None:
    class DummyClient:
        def search_assignable_users(self, query: str, *, project_key: str | None = None, max_results: int = 20) -> list[dict]:
            return [
                {
                    "accountId": "customer-1",
                    "displayName": "Karim Benali",
                    "emailAddress": "agent@teamwill.com",
                    "accountType": "customer",
                    "active": True,
                },
                {
                    "accountId": "licensed-1",
                    "displayName": "Karim Benali",
                    "emailAddress": "agent@teamwill.com",
                    "accountType": "atlassian",
                    "active": True,
                },
            ]

    account_id = _find_best_account_id(
        DummyClient(),
        raw="Karim Benali",
        queries=["Karim Benali"],
        assignable=True,
        project_key="TEAMWILL",
    )

    assert account_id == "licensed-1"
