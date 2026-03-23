"""Reset the local mock dataset with a deterministic 40-ticket seed.

This script is intentionally local-only:
- no Jira push
- no reconcile
- no network calls
- quick verification output only
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.ai_sla_risk_evaluation import AiSlaRiskEvaluation  # noqa: E402
from app.models.automation_event import AutomationEvent  # noqa: E402
from app.models.enums import (  # noqa: E402
    ProblemStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from app.models.notification import Notification  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.models.recommendation import Recommendation  # noqa: E402
from app.models.ticket import Ticket, TicketComment  # noqa: E402

UTC = dt.timezone.utc
REFERENCE_NOW = dt.datetime(2026, 3, 14, 9, 0, tzinfo=UTC)
ACTIVE_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.pending,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
}

ASSIGNEES = [
    "Karim Benali",
    "Amina Rafi",
    "Youssef Hamdi",
    "Nadia Boucher",
    "Leila Ben Amor",
    "Mohamed Chaari",
    "Rania Gharbi",
    "Yassine Trabelsi",
]

REPORTERS = [
    "Maya Haddad",
    "Sophie Leclerc",
    "Admin TeamWill",
    "Finance Team",
    "HR Team",
    "Support Desk",
    "Sales Ops",
    "Procurement Team",
]

PROBLEMS = [
    {
        "id": "PB-MOCK-01",
        "title": "Recurring remote access instability on TeamWill VPN",
        "category": TicketCategory.network,
        "status": ProblemStatus.investigating,
        "created_at": dt.datetime(2026, 3, 8, 8, 0, tzinfo=UTC),
        "updated_at": dt.datetime(2026, 3, 14, 8, 30, tzinfo=UTC),
        "last_seen_at": dt.datetime(2026, 3, 14, 8, 30, tzinfo=UTC),
        "resolved_at": None,
        "root_cause": "A recent VPN policy cleanup left the MFA session timeout and split-tunnel routes out of sync for several user groups.",
        "workaround": "Refresh the VPN profile bundle, restart stale sessions, and bypass the shortest MFA policy for the affected teams during triage.",
        "permanent_fix": "Align the MFA session lifetime with the VPN profile, restore the approved split-tunnel routes, and add a post-change VPN smoke test.",
        "similarity_key": "network|mock|vpn-remote-access-instability",
    },
    {
        "id": "PB-MOCK-02",
        "title": "Recurring mail relay and notification delivery failures",
        "category": TicketCategory.email,
        "status": ProblemStatus.known_error,
        "created_at": dt.datetime(2026, 3, 7, 9, 15, tzinfo=UTC),
        "updated_at": dt.datetime(2026, 3, 14, 8, 45, tzinfo=UTC),
        "last_seen_at": dt.datetime(2026, 3, 14, 8, 45, tzinfo=UTC),
        "resolved_at": None,
        "root_cause": "Mail workers are not refreshing the relay trust store consistently after certificate renewals, which breaks queue processing and connector-based delivery.",
        "workaround": "Route urgent traffic through the backup relay, redeploy the approved CA bundle, and flush the deferred queue before restoring normal flow.",
        "permanent_fix": "Automate trust-store rollout validation, block stale connector identities, and add a health check for relay chain drift.",
        "similarity_key": "email|mock|mail-relay-notification-failures",
    },
]

INCIDENT_SCENARIOS: list[dict[str, object]] = []
SERVICE_REQUEST_SCENARIOS: list[dict[str, object]] = []

INCIDENT_SCENARIOS.extend(
    [
        {
            "title": "VPN login loops after MFA for finance users",
            "description": "Finance users complete MFA but the VPN client returns them to the sign-in prompt instead of opening a session.",
            "category": TicketCategory.network,
            "priority": TicketPriority.critical,
            "problem_id": "PB-MOCK-01",
            "action": "review the finance VPN conditional access policy and session timeout",
            "fix": "aligned the finance VPN timeout with the MFA session policy",
            "tags": ["vpn", "mfa", "finance"],
        },
        {
            "title": "Password reset emails delayed by SMTP queue backlog",
            "description": "Password reset emails are delayed for more than twenty minutes because the primary SMTP relay queue keeps growing after a certificate renewal.",
            "category": TicketCategory.email,
            "priority": TicketPriority.high,
            "problem_id": "PB-MOCK-02",
            "action": "redeploy the approved relay certificate chain and inspect queue growth",
            "fix": "installed the missing CA bundle and drained the deferred SMTP queue",
            "tags": ["smtp", "queue", "password-reset"],
        },
        {
            "title": "HR portal returns 500 during manager approvals",
            "description": "Managers can open leave requests, but approving them triggers a 500 error on the HR portal confirmation step.",
            "category": TicketCategory.application,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "trace the approval endpoint and compare the latest deployment changes",
            "fix": "patched the approval serializer and redeployed the portal API",
            "tags": ["hr-portal", "approval", "api"],
        },
        {
            "title": "Warehouse printer offline on the shipping floor",
            "description": "The main shipping printer shows as offline and the warehouse team cannot print packing slips for outgoing orders.",
            "category": TicketCategory.hardware,
            "priority": TicketPriority.medium,
            "problem_id": None,
            "action": "check the printer network link and replace the failed component if needed",
            "fix": "replaced the failed network card and restored printer connectivity",
            "tags": ["printer", "warehouse", "hardware"],
        },
        {
            "title": "Shared mailbox stops forwarding to Teams channel",
            "description": "Messages still reach the shared mailbox, but the connector that posts updates into Teams stopped forwarding them after rotation.",
            "category": TicketCategory.email,
            "priority": TicketPriority.medium,
            "problem_id": "PB-MOCK-02",
            "action": "verify the forwarding connector identity and reauthorize the Teams webhook",
            "fix": "rebuilt the forwarding rule with the current connector identity",
            "tags": ["mailbox", "teams", "forwarding"],
        },
        {
            "title": "VPN split tunnel no longer reaches ERP subnet",
            "description": "Remote users connect to VPN successfully, but traffic for the ERP subnet is missing from the split-tunnel route bundle.",
            "category": TicketCategory.network,
            "priority": TicketPriority.high,
            "problem_id": "PB-MOCK-01",
            "action": "compare the deployed split-tunnel routes with the approved ERP route set",
            "fix": "restored the ERP routes to the VPN split-tunnel configuration",
            "tags": ["vpn", "erp", "routing"],
        },
        {
            "title": "Finance dashboard export fails after overnight patch",
            "description": "Finance analysts can load the dashboard, but the export button now returns an application error after last night's patch.",
            "category": TicketCategory.application,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "review the export service logs and rollback the failing patch if required",
            "fix": "reverted the broken export patch and replayed the failed job",
            "tags": ["finance", "dashboard", "export"],
        },
        {
            "title": "Training room Wi-Fi drops every ten minutes",
            "description": "Devices in the training room connect normally, then lose Wi-Fi around every ten minutes during active sessions.",
            "category": TicketCategory.network,
            "priority": TicketPriority.medium,
            "problem_id": None,
            "action": "inspect access point roaming and radio settings in the training room",
            "fix": "stabilized the access point channel plan and disabled the faulty roaming profile",
            "tags": ["wifi", "training-room", "network"],
        },
        {
            "title": "Laptop encryption policy blocks boot after restart",
            "description": "A patched laptop restarts into the recovery screen because the latest encryption policy did not finish key escrow before enforcement.",
            "category": TicketCategory.security,
            "priority": TicketPriority.critical,
            "problem_id": None,
            "action": "compare the encryption policy rollout with device escrow status",
            "fix": "reordered the escrow step before the encryption enforcement policy",
            "tags": ["laptop", "encryption", "policy"],
        },
        {
            "title": "CRM sync job stalls after token rotation",
            "description": "The scheduled CRM sync starts on time, but it stalls after token rotation and never writes the latest contact updates.",
            "category": TicketCategory.infrastructure,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "refresh the integration token and inspect the stalled worker logs",
            "fix": "rotated the worker secret and restarted the stalled sync worker",
            "tags": ["crm", "sync", "worker"],
        },
    ]
)

SERVICE_REQUEST_SCENARIOS.extend(
    [
        {
            "title": "Provision laptop and dock for a new starter",
            "description": "Prepare a laptop, docking station, and standard software profile for the new starter joining the finance team next week.",
            "category": TicketCategory.hardware,
            "priority": TicketPriority.medium,
            "action": "image the laptop and schedule the dock handoff with the hiring manager",
            "fix": "imaged the laptop and confirmed the hardware handoff with the hiring manager",
            "tags": ["onboarding", "laptop", "dock"],
        },
        {
            "title": "Create finance shared mailbox for approvals",
            "description": "Create a moderated finance shared mailbox for approval requests and grant access to the approved finance leads.",
            "category": TicketCategory.email,
            "priority": TicketPriority.medium,
            "action": "create the shared mailbox and validate delegate permissions",
            "fix": "created the mailbox and confirmed delegate access for the finance leads",
            "tags": ["shared-mailbox", "finance", "approvals"],
        },
        {
            "title": "Grant VPN access for an external auditor",
            "description": "Provide time-boxed VPN access for the external auditor and apply the approved read-only route restrictions.",
            "category": TicketCategory.service_request,
            "priority": TicketPriority.high,
            "action": "apply the approved auditor access group and validate time-boxed expiry",
            "fix": "granted the auditor VPN access with the approved read-only route policy",
            "tags": ["vpn-access", "auditor", "temporary"],
        },
        {
            "title": "Install design software on a marketing laptop",
            "description": "Install the approved design software bundle on the marketing laptop and confirm the license assignment.",
            "category": TicketCategory.application,
            "priority": TicketPriority.medium,
            "action": "assign the design license and complete the workstation install",
            "fix": "installed the design bundle and assigned the correct license",
            "tags": ["software", "marketing", "license"],
        },
        {
            "title": "Add HR director to the restricted report folder",
            "description": "Grant the HR director access to the restricted report folder and verify the folder inherits the intended security group.",
            "category": TicketCategory.security,
            "priority": TicketPriority.high,
            "action": "update the security group membership and validate folder inheritance",
            "fix": "updated the security group membership and verified folder access",
            "tags": ["hr", "permissions", "folder"],
        },
        {
            "title": "Create distribution list for the ops war room",
            "description": "Create a new ops-war-room distribution list for incident updates and add the approved engineering roster.",
            "category": TicketCategory.email,
            "priority": TicketPriority.low,
            "action": "create the distribution list and validate the approved roster",
            "fix": "created the distribution list and confirmed mail flow to all approved members",
            "tags": ["distribution-list", "ops", "email"],
        },
        {
            "title": "Set up a meeting room tablet for the fourth floor",
            "description": "Prepare and enroll a meeting room tablet for the fourth floor boardroom with the standard room-booking profile.",
            "category": TicketCategory.hardware,
            "priority": TicketPriority.medium,
            "action": "enroll the tablet and apply the standard room-booking profile",
            "fix": "enrolled the room tablet and confirmed the booking profile is active",
            "tags": ["tablet", "meeting-room", "enrollment"],
        },
        {
            "title": "Enable read-only database access for the analytics intern",
            "description": "Provision a read-only database account for the analytics intern and restrict it to the approved reporting schemas.",
            "category": TicketCategory.infrastructure,
            "priority": TicketPriority.high,
            "action": "create the restricted database role and verify schema-level access",
            "fix": "provisioned the read-only role and verified the approved reporting schemas",
            "tags": ["database", "analytics", "read-only"],
        },
        {
            "title": "Increase storage quota for the legal archive share",
            "description": "Increase the legal archive share quota to match the approved request and confirm the alert threshold is still active.",
            "category": TicketCategory.infrastructure,
            "priority": TicketPriority.medium,
            "action": "expand the share quota and validate the archive alert threshold",
            "fix": "expanded the legal share quota and confirmed the alert threshold",
            "tags": ["storage", "archive", "quota"],
        },
        {
            "title": "Create Jira dashboard for weekly SLA review",
            "description": "Build a Jira dashboard for the weekly SLA review with widgets for due tickets, breached SLA, and ticket aging.",
            "category": TicketCategory.application,
            "priority": TicketPriority.medium,
            "action": "assemble the SLA widgets and share the dashboard with the review team",
            "fix": "published the SLA dashboard and shared it with the review team",
            "tags": ["jira", "dashboard", "sla"],
        },
    ]
)

SERVICE_REQUEST_SCENARIOS.extend(
    [
        {
            "title": "Add SharePoint members for procurement workspace",
            "description": "Add the approved members to the procurement SharePoint workspace and confirm inherited document access.",
            "category": TicketCategory.service_request,
            "priority": TicketPriority.medium,
            "action": "update workspace membership and validate inherited document access",
            "fix": "updated workspace membership and confirmed the expected document access",
            "tags": ["sharepoint", "procurement", "membership"],
        },
        {
            "title": "Replace keyboard and dock for a finance analyst",
            "description": "Replace the faulty keyboard and dock used by a finance analyst and verify the peripherals work at the assigned desk.",
            "category": TicketCategory.hardware,
            "priority": TicketPriority.low,
            "action": "swap the faulty peripherals and test them at the assigned desk",
            "fix": "replaced the keyboard and dock and validated desk connectivity",
            "tags": ["peripherals", "finance", "desk"],
        },
        {
            "title": "Schedule printer access for the new branch office",
            "description": "Grant the new branch office users access to the approved printer queue and publish the driver package.",
            "category": TicketCategory.service_request,
            "priority": TicketPriority.medium,
            "action": "publish the printer queue and assign the branch office access group",
            "fix": "published the printer queue and confirmed branch office access",
            "tags": ["printer-access", "branch", "drivers"],
        },
        {
            "title": "Provision service account for the SFTP import job",
            "description": "Create a service account for the nightly SFTP import job and apply the approved secret rotation policy.",
            "category": TicketCategory.security,
            "priority": TicketPriority.high,
            "action": "create the service identity and attach the secret rotation policy",
            "fix": "provisioned the service account and enabled the approved rotation policy",
            "tags": ["service-account", "sftp", "rotation"],
        },
        {
            "title": "Configure SSO in sandbox for the QA team",
            "description": "Configure sandbox SSO for the QA team so they can test the latest identity changes without touching production.",
            "category": TicketCategory.application,
            "priority": TicketPriority.high,
            "action": "link the sandbox app to the QA identity group and validate login flow",
            "fix": "configured sandbox SSO and verified login flow for the QA group",
            "tags": ["sso", "sandbox", "qa"],
        },
        {
            "title": "Prepare audit evidence export package",
            "description": "Assemble the approved audit evidence export package and place it in the secure handoff location for compliance review.",
            "category": TicketCategory.application,
            "priority": TicketPriority.medium,
            "action": "collect the approved evidence files and stage the secure export",
            "fix": "assembled the evidence package and completed the secure handoff",
            "tags": ["audit", "export", "compliance"],
        },
        {
            "title": "Grant temporary admin rights on a staging VM",
            "description": "Provide temporary staging admin rights for a release engineer and enable command auditing for the full elevation window.",
            "category": TicketCategory.security,
            "priority": TicketPriority.high,
            "action": "grant time-boxed admin rights and verify command auditing is active",
            "fix": "granted time-boxed admin rights and confirmed command auditing",
            "tags": ["admin-access", "staging", "audit"],
        },
        {
            "title": "Create webhook rotation reminder task",
            "description": "Create a recurring task that reminds the integrations team to rotate the webhook secret on the approved cadence.",
            "category": TicketCategory.service_request,
            "priority": TicketPriority.low,
            "action": "schedule the reminder task and confirm the integrations team subscription",
            "fix": "scheduled the webhook reminder task and confirmed the team subscription",
            "tags": ["webhook", "rotation", "reminder"],
        },
        {
            "title": "Provision a mobile hotspot for a field engineer",
            "description": "Prepare a mobile hotspot for the field engineer and activate the approved roaming profile before the site visit.",
            "category": TicketCategory.service_request,
            "priority": TicketPriority.medium,
            "action": "activate the hotspot profile and validate roaming before shipment",
            "fix": "activated the hotspot profile and confirmed roaming coverage",
            "tags": ["hotspot", "field-engineer", "roaming"],
        },
        {
            "title": "Add payroll distribution rule for approval notices",
            "description": "Create a payroll distribution rule for approval notices and confirm the approved managers receive the expected messages.",
            "category": TicketCategory.email,
            "priority": TicketPriority.medium,
            "action": "build the distribution rule and validate the manager recipient list",
            "fix": "created the payroll distribution rule and verified recipient delivery",
            "tags": ["payroll", "distribution", "notifications"],
        },
    ]
)

INCIDENT_SCENARIOS.extend(
    [
        {
            "title": "Remote consultants disconnect during VPN handoff",
            "description": "Consultants authenticate successfully, then drop during the VPN handoff right before the desktop pool becomes reachable.",
            "category": TicketCategory.network,
            "priority": TicketPriority.critical,
            "problem_id": "PB-MOCK-01",
            "action": "inspect session handoff timing between VPN and the desktop gateway",
            "fix": "increased the handoff window and cleared stale VPN sessions",
            "tags": ["vpn", "consultants", "session"],
        },
        {
            "title": "Ticket notifications fail after relay certificate renewal",
            "description": "Customer replies still create tickets, but outbound ticket notifications stopped leaving the mail relay after the certificate renewal.",
            "category": TicketCategory.email,
            "priority": TicketPriority.critical,
            "problem_id": "PB-MOCK-02",
            "action": "redeploy stale mail workers and validate the renewed relay trust chain",
            "fix": "redeployed stale mail workers with the correct relay trust chain",
            "tags": ["notifications", "relay", "certificate"],
        },
        {
            "title": "Payroll export CSV writes broken date values",
            "description": "The payroll export CSV is generated, but date columns contain malformed values that cannot be imported into the finance workbook.",
            "category": TicketCategory.application,
            "priority": TicketPriority.medium,
            "problem_id": None,
            "action": "inspect the CSV formatter and compare the date serialization change",
            "fix": "corrected the CSV date formatter and regenerated the payroll export",
            "tags": ["payroll", "csv", "export"],
        },
        {
            "title": "Legal archive access returns permission denied",
            "description": "The legal team can open the archive root, but all protected folders underneath return permission denied for authorized users.",
            "category": TicketCategory.security,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "review the archive access control changes and restore the intended group mapping",
            "fix": "restored the archive ACL mapping for the approved legal security group",
            "tags": ["archive", "permissions", "legal"],
        },
        {
            "title": "Backup monitor sends duplicate failure alarms",
            "description": "The backup jobs are healthy, but the monitoring rule sends duplicate failure alarms every hour to the operations channel.",
            "category": TicketCategory.infrastructure,
            "priority": TicketPriority.medium,
            "problem_id": None,
            "action": "adjust the monitor deduplication rule and inspect the alert payload",
            "fix": "corrected the deduplication key used by the backup monitor",
            "tags": ["backup", "alerts", "monitoring"],
        },
        {
            "title": "Contractor VPN sessions rejected after policy update",
            "description": "Contractor accounts that worked last week are now rejected by the VPN gateway after a route policy update.",
            "category": TicketCategory.network,
            "priority": TicketPriority.high,
            "problem_id": "PB-MOCK-01",
            "action": "compare the contractor access policy with the previous working route set",
            "fix": "restored the contractor route policy and reloaded the VPN profile bundle",
            "tags": ["vpn", "contractor", "policy"],
        },
        {
            "title": "Procurement scanner not detected on service desk workstation",
            "description": "The procurement barcode scanner powers on, but the service desk workstation no longer detects it as an input device.",
            "category": TicketCategory.hardware,
            "priority": TicketPriority.medium,
            "problem_id": None,
            "action": "replace the USB driver package and test the scanner on a clean profile",
            "fix": "reinstalled the scanner driver package and confirmed device detection",
            "tags": ["scanner", "procurement", "usb"],
        },
        {
            "title": "Vendor replies land in junk from shared mailbox",
            "description": "Replies sent from the vendor shared mailbox are delivered, but recipient systems route them to junk after the latest relay identity change.",
            "category": TicketCategory.email,
            "priority": TicketPriority.high,
            "problem_id": "PB-MOCK-02",
            "action": "inspect the relay identity alignment and DKIM configuration for the shared mailbox",
            "fix": "realigned the relay identity and refreshed the mailbox DKIM configuration",
            "tags": ["email", "shared-mailbox", "deliverability"],
        },
        {
            "title": "Remote desktop sessions freeze on jump host pool",
            "description": "Jump host sessions connect successfully, but they freeze after a few minutes whenever admins open infrastructure tools.",
            "category": TicketCategory.infrastructure,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "review the jump host resource pool and recent GPU policy changes",
            "fix": "increased jump host resources and rolled back the conflicting GPU policy",
            "tags": ["rdp", "jump-host", "performance"],
        },
        {
            "title": "Customer portal drops uploaded attachments on submit",
            "description": "Customers can select attachments in the portal, but the files disappear after they submit the form and the case is created without them.",
            "category": TicketCategory.application,
            "priority": TicketPriority.high,
            "problem_id": None,
            "action": "trace the upload handoff between the form service and object storage",
            "fix": "restored the upload handoff and validated attachments in the case workflow",
            "tags": ["portal", "attachments", "upload"],
        },
    ]
)

RESOLVED_BREACHED_IDS = {6, 15, 24, 33, 39}
ACTIVE_BREACHED_IDS = {5, 10, 20, 25, 35, 40}


def pick_status(index: int) -> TicketStatus:
    remainder = index % 3
    if remainder == 1:
        return TicketStatus.open
    if remainder == 2:
        return TicketStatus.in_progress
    return TicketStatus.resolved


def pick_sla_status(index: int, status: TicketStatus) -> str:
    if status == TicketStatus.resolved:
        if index in RESOLVED_BREACHED_IDS:
            return "breached"
        return "completed"
    if index in ACTIVE_BREACHED_IDS:
        return "breached"
    if index % 2 == 0:
        return "at_risk"
    return "ok"


def build_ticket_payloads() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position in range(20):
        rows.append({"ticket_type": TicketType.incident, **INCIDENT_SCENARIOS[position]})
        rows.append({"ticket_type": TicketType.service_request, **SERVICE_REQUEST_SCENARIOS[position]})
    return rows


def comment_times(index: int, created_at: dt.datetime, status: TicketStatus) -> tuple[dt.datetime, dt.datetime, dt.datetime | None]:
    first = created_at + dt.timedelta(minutes=75 + ((index - 1) % 4) * 15)
    if status == TicketStatus.resolved:
        second = created_at + dt.timedelta(hours=8 + ((index - 1) % 5))
        resolved_at = second + dt.timedelta(minutes=25)
        return first, second, resolved_at
    second = created_at + dt.timedelta(hours=4 + ((index - 1) % 4))
    return first, second, None


def due_at_for(index: int, status: TicketStatus, sla_status: str, resolved_at: dt.datetime | None) -> dt.datetime:
    if status == TicketStatus.resolved and resolved_at is not None:
        if sla_status == "completed":
            return resolved_at + dt.timedelta(hours=6 + (index % 5))
        return resolved_at - dt.timedelta(hours=2 + (index % 4))
    if sla_status == "breached":
        return REFERENCE_NOW - dt.timedelta(hours=2 + (index % 5))
    if sla_status == "at_risk":
        return REFERENCE_NOW + dt.timedelta(hours=1 + (index % 3))
    return REFERENCE_NOW + dt.timedelta(days=2 + (index % 4), hours=index % 5)


def build_comment_payloads(ticket_id: str, assignee: str, reporter: str, row: dict[str, object], status: TicketStatus) -> list[dict[str, object]]:
    description = str(row["description"])
    action = str(row["action"])
    fix = str(row["fix"])
    first = row["first_comment_at"]
    second = row["second_comment_at"]
    comments = [
        {
            "id": f"{ticket_id}-C1",
            "author": reporter,
            "content": f"Reporter note for {ticket_id}: {description} This needs an obvious mock follow-up.",
            "created_at": first,
        },
    ]
    if status == TicketStatus.resolved:
        comments.append(
            {
                "id": f"{ticket_id}-C2",
                "author": assignee,
                "content": f"Assignee note for {ticket_id}: {fix}. Resolution has been verified with the requester.",
                "created_at": second,
            }
        )
    else:
        comments.append(
            {
                "id": f"{ticket_id}-C2",
                "author": assignee,
                "content": f"Assignee note for {ticket_id}: triage is active and the next step is to {action}.",
                "created_at": second,
            }
        )
    return comments


def purge_existing_data(db) -> None:  # noqa: ANN001
    db.query(AiSlaRiskEvaluation).delete(synchronize_session=False)
    db.query(AutomationEvent).delete(synchronize_session=False)
    db.query(Recommendation).delete(synchronize_session=False)
    db.query(Notification).delete(synchronize_session=False)
    db.query(TicketComment).delete(synchronize_session=False)
    db.query(Ticket).delete(synchronize_session=False)
    db.query(Problem).delete(synchronize_session=False)
    db.commit()


def seed_problems(db) -> None:  # noqa: ANN001
    for row in PROBLEMS:
        db.add(
            Problem(
                id=row["id"],
                title=row["title"],
                category=row["category"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                last_seen_at=row["last_seen_at"],
                resolved_at=row["resolved_at"],
                occurrences_count=0,
                active_count=0,
                root_cause=row["root_cause"],
                workaround=row["workaround"],
                permanent_fix=row["permanent_fix"],
                similarity_key=row["similarity_key"],
            )
        )


def seed_tickets_and_comments(db) -> None:  # noqa: ANN001
    for index, payload in enumerate(build_ticket_payloads(), start=1):
        ticket_id = f"TW-MOCK-{index:03d}"
        status = pick_status(index)
        sla_status = pick_sla_status(index, status)
        assignee = ASSIGNEES[(index - 1) % len(ASSIGNEES)]
        reporter = REPORTERS[(index - 1) % len(REPORTERS)]
        created_at = REFERENCE_NOW - dt.timedelta(days=(index % 9) + 1, hours=((index - 1) % 5) * 2)
        first_comment_at, second_comment_at, resolved_at = comment_times(index, created_at, status)
        due_at = due_at_for(index, status, sla_status, resolved_at)
        updated_at = resolved_at or second_comment_at
        first_response_due_at = created_at + dt.timedelta(hours=2)
        resolution = None
        if status == TicketStatus.resolved:
            resolution = f"Resolved by {payload['fix']}; requester confirmed the expected outcome."

        row = {
            **payload,
            "created_at": created_at,
            "updated_at": updated_at,
            "first_comment_at": first_comment_at,
            "second_comment_at": second_comment_at,
            "resolved_at": resolved_at,
            "description": payload["description"],
            "action": payload["action"],
            "fix": payload["fix"],
        }
        comments = build_comment_payloads(ticket_id, assignee, reporter, row, status)

        ticket = Ticket(
            id=ticket_id,
            title=str(payload["title"]),
            description=str(payload["description"]),
            status=status,
            priority=payload["priority"],
            ticket_type=payload["ticket_type"],
            category=payload["category"],
            assignee=assignee,
            reporter=reporter,
            reporter_id=None,
            problem_id=payload.get("problem_id"),
            auto_assignment_applied=False,
            auto_priority_applied=False,
            assignment_model_version="mock-reset-v1",
            priority_model_version="mock-reset-v1",
            predicted_priority=payload["priority"],
            predicted_ticket_type=payload["ticket_type"],
            predicted_category=payload["category"],
            assignment_change_count=0,
            first_action_at=first_comment_at,
            resolved_at=resolved_at,
            created_at=created_at,
            updated_at=updated_at,
            source="local",
            jira_key=None,
            jira_issue_id=None,
            jira_created_at=None,
            jira_updated_at=None,
            external_id=None,
            external_source=None,
            external_updated_at=None,
            last_synced_at=None,
            due_at=due_at,
            raw_payload=None,
            jira_sla_payload=None,
            sla_status=sla_status,
            sla_first_response_due_at=first_response_due_at,
            sla_resolution_due_at=due_at,
            sla_first_response_breached=first_comment_at > first_response_due_at,
            sla_resolution_breached=sla_status == "breached",
            sla_first_response_completed_at=first_comment_at,
            sla_resolution_completed_at=resolved_at,
            sla_remaining_minutes=int(((due_at - (resolved_at or REFERENCE_NOW)).total_seconds()) // 60),
            sla_elapsed_minutes=int((((resolved_at or REFERENCE_NOW) - created_at).total_seconds()) // 60),
            sla_last_synced_at=updated_at,
            priority_auto_escalated=False,
            priority_escalation_reason=None,
            priority_escalated_at=None,
            resolution=resolution,
            tags=["mock", payload["ticket_type"].value, *list(payload["tags"])],
        )
        db.add(ticket)

        for comment in comments:
            db.add(
                TicketComment(
                    id=str(comment["id"]),
                    ticket_id=ticket_id,
                    author=str(comment["author"]),
                    content=str(comment["content"]),
                    created_at=comment["created_at"],
                    updated_at=None,
                    jira_comment_id=None,
                    jira_created_at=None,
                    jira_updated_at=None,
                    external_comment_id=None,
                    external_source=None,
                    external_updated_at=None,
                    raw_payload=None,
                )
            )


def refresh_problem_counters(db) -> None:  # noqa: ANN001
    for problem in db.query(Problem).order_by(Problem.id.asc()).all():
        linked = db.query(Ticket).filter(Ticket.problem_id == problem.id).all()
        problem.occurrences_count = len(linked)
        problem.active_count = sum(1 for ticket in linked if ticket.status in ACTIVE_STATUSES)
        if linked:
            latest = max(ticket.updated_at for ticket in linked)
            problem.last_seen_at = latest
            problem.updated_at = latest
        db.add(problem)


def summarize(db) -> dict[str, object]:  # noqa: ANN001
    tickets = db.query(Ticket).order_by(Ticket.id.asc()).all()
    comments = db.query(TicketComment).count()
    problems = db.query(Problem).count()
    by_type = Counter(ticket.ticket_type.value for ticket in tickets)
    by_status = Counter(ticket.status.value for ticket in tickets)
    by_sla = Counter((ticket.sla_status or "unknown") for ticket in tickets)
    due_at_count = sum(1 for ticket in tickets if ticket.due_at is not None)
    resolved_with_resolution = sum(
        1
        for ticket in tickets
        if ticket.status == TicketStatus.resolved and bool((ticket.resolution or "").strip())
    )
    linked_problem_tickets = sum(1 for ticket in tickets if ticket.problem_id)
    return {
        "tickets": len(tickets),
        "comments": comments,
        "problems": problems,
        "ticket_type_breakdown": dict(sorted(by_type.items())),
        "status_breakdown": dict(sorted(by_status.items())),
        "sla_breakdown": dict(sorted(by_sla.items())),
        "tickets_with_due_at": due_at_count,
        "resolved_tickets_with_resolution": resolved_with_resolution,
        "tickets_linked_to_problems": linked_problem_tickets,
    }


def main() -> int:
    db = SessionLocal()
    try:
        purge_existing_data(db)
        seed_problems(db)
        seed_tickets_and_comments(db)
        db.flush()
        refresh_problem_counters(db)
        db.commit()
        summary = summarize(db)
    finally:
        db.close()

    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
