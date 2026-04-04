from __future__ import annotations

from app.integrations.jira.mapper import map_category, map_issue, map_issue_comment, map_priority, map_status
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType


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
    assert mapped.ticket_type == TicketType.incident


def test_status_priority_mapping_unknown_defaults() -> None:
    fields = {"status": {"name": "SomethingElse", "statusCategory": {"key": ""}}, "priority": {"name": "UnknownPriority"}}
    assert map_status(fields) == TicketStatus.open
    assert map_priority(fields) == TicketPriority.medium


def test_status_mapping_waiting_states() -> None:
    waiting_customer_fields = {"status": {"name": "Waiting for Customer", "statusCategory": {"key": "indeterminate"}}}
    waiting_support_fields = {"status": {"name": "Waiting for Support", "statusCategory": {"key": "indeterminate"}}}
    waiting_vendor_fields = {"status": {"name": "Waiting for Vendor", "statusCategory": {"key": "indeterminate"}}}
    done_fields = {"status": {"name": "Done", "statusCategory": {"key": "done"}}}

    assert map_status(waiting_customer_fields) == TicketStatus.waiting_for_customer
    assert map_status(waiting_support_fields) == TicketStatus.open
    assert map_status(waiting_vendor_fields) == TicketStatus.waiting_for_support_vendor
    assert map_status(done_fields) == TicketStatus.resolved


def test_map_issue_strips_local_ticket_prefixes_from_summary() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["summary"] = "[TW-1008] [TW-1008] Mise a jour du framework Angular vers v19"

    mapped = map_issue(issue)

    assert mapped.title == "Mise a jour du framework Angular vers v19"


def test_map_issue_collapses_duplicate_legacy_prefixes_from_summary() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["summary"] = "[JSM-HP-36] [JSM-HP-36] [TW-1031] Troubleshooting AWS Clustering Issue"

    mapped = map_issue(issue)

    assert mapped.title == "[JSM-HP-36] [TW-1031] Troubleshooting AWS Clustering Issue"


def test_map_issue_maps_email_request_to_service_request_type() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["issuetype"] = {"name": "Email Request"}

    mapped = map_issue(issue)

    assert mapped.ticket_type == TicketType.service_request


def test_map_issue_does_not_map_incident_issue_type_to_service_request_category() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")

    mapped = map_issue(issue)

    assert mapped.ticket_type == TicketType.incident
    assert mapped.category != TicketCategory.service_request


def test_map_issue_prefers_request_type_field_for_ticket_type() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["issuetype"] = {"name": "[System] Service request"}
    issue["fields"]["customfield_10010"] = {
        "requestType": {
            "id": "14",
            "name": "Report a system problem",
            "issueTypeId": "10001",
        }
    }

    mapped = map_issue(issue)

    assert mapped.ticket_type == TicketType.incident


def test_map_issue_reads_due_date_field() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["duedate"] = "2026-03-20"

    mapped = map_issue(issue)

    assert mapped.due_at is not None
    assert mapped.due_at.date().isoformat() == "2026-03-20"


def test_map_issue_prefers_managed_local_assignee_label_over_native_assignee() -> None:
    issue = _issue_payload(status_name="Open", priority_name="Medium")
    issue["fields"]["assignee"] = {"displayName": "Youssef Jmel"}
    issue["fields"]["labels"] = ["local_assignee_youssef_hamdi"]

    mapped = map_issue(issue)

    assert mapped.assignee == "Youssef Hamdi"


def test_map_category_prefers_category_label_over_request_type() -> None:
    fields = {
        "labels": ["category_network"],
        "components": [{"name": "Hardware"}],
        "customfield_10010": {
            "requestType": {
                "id": "14",
                "name": "Request new software",
                "issueTypeId": "10002",
            }
        },
        "issuetype": {"name": "[System] Service request"},
    }

    assert map_category(fields).value == "network"


def test_map_category_reads_managed_category_component() -> None:
    fields = {
        "labels": [],
        "components": [{"name": "Security"}],
        "customfield_10010": {
            "requestType": {
                "id": "14",
                "name": "Get IT help",
                "issueTypeId": "10002",
            }
        },
        "issuetype": {"name": "[System] Service request"},
    }

    assert map_category(fields).value == "security"


def test_map_category_infers_hardware_from_mobile_hotspot_request_text() -> None:
    fields = {
        "summary": "Provision a mobile hotspot for a field engineer",
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Prepare a mobile hotspot for the field engineer and activate the approved roaming profile before the site visit.",
                        }
                    ],
                }
            ],
        },
        "labels": [],
        "components": [],
        "customfield_10010": {
            "requestType": {
                "id": "14",
                "name": "Service Request",
                "issueTypeId": "10002",
            }
        },
        "issuetype": {"name": "Service Request"},
    }

    assert map_category(fields).value == "hardware"


def test_map_category_infers_application_from_dashboard_build_request_text() -> None:
    fields = {
        "summary": "Build a SLA dashboard for the weekly review",
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Build a dashboard for the weekly SLA review with widgets for due tickets, breached SLA, and ticket aging.",
                        }
                    ],
                }
            ],
        },
        "labels": [],
        "components": [],
        "customfield_10010": {
            "requestType": {
                "id": "14",
                "name": "Service Request",
                "issueTypeId": "10002",
            }
        },
        "issuetype": {"name": "Service Request"},
    }

    assert map_category(fields).value == "application"


def test_map_issue_comment_restores_prefixed_platform_author() -> None:
    comment = {
        "id": "10093",
        "author": {"displayName": "Youssef Jmel"},
        "body": {
            "type": "doc",
            "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "[Platform author: Karim Benali]"},
                        ],
                    },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Please review the VPN gateway logs."},
                    ],
                },
            ],
        },
        "created": "2026-02-14T10:00:00.000+0000",
        "updated": "2026-02-14T11:00:00.000+0000",
    }

    mapped = map_issue_comment(comment)

    assert mapped.author == "Karim Benali"
    assert mapped.content == "Please review the VPN gateway logs."
