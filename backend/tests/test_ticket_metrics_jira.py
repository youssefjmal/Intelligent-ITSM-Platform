from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.services.tickets import compute_assignment_performance, compute_problem_insights, compute_stats


def _ticket(  # noqa: PLR0913
    *,
    ticket_id: str,
    status: TicketStatus,
    created_at: dt.datetime,
    updated_at: dt.datetime,
    jira_created_at: dt.datetime | None = None,
    jira_updated_at: dt.datetime | None = None,
    first_action_at: dt.datetime | None = None,
    resolved_at: dt.datetime | None = None,
    problem_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=ticket_id,
        title=f"Ticket {ticket_id}",
        description="desc",
        status=status,
        priority=TicketPriority.medium,
        category=TicketCategory.network,
        assignee="Agent",
        reporter="Reporter",
        created_at=created_at,
        updated_at=updated_at,
        jira_created_at=jira_created_at,
        jira_updated_at=jira_updated_at,
        first_action_at=first_action_at,
        resolved_at=resolved_at,
        assignment_change_count=0,
        auto_assignment_applied=False,
        auto_priority_applied=False,
        predicted_priority=None,
        predicted_category=None,
        resolution=None,
        problem_id=problem_id,
    )


def test_stats_use_jira_timestamps_for_resolution_duration() -> None:
    now = dt.datetime(2026, 2, 15, 12, 0, tzinfo=dt.timezone.utc)
    ticket = _ticket(
        ticket_id="JSM-1",
        status=TicketStatus.resolved,
        created_at=now,
        updated_at=now,
        jira_created_at=now - dt.timedelta(days=2),
        jira_updated_at=now - dt.timedelta(days=1),
    )

    stats = compute_stats([ticket])

    assert stats["resolved"] == 1
    assert stats["avg_resolution_days"] == 1.0


def test_performance_uses_jira_created_at_for_first_action() -> None:
    now = dt.datetime(2026, 2, 15, 12, 0, tzinfo=dt.timezone.utc)
    ticket = _ticket(
        ticket_id="JSM-2",
        status=TicketStatus.in_progress,
        created_at=now,
        updated_at=now,
        jira_created_at=now - dt.timedelta(hours=4),
        jira_updated_at=now - dt.timedelta(hours=2),
        first_action_at=now - dt.timedelta(hours=3),
    )

    metrics = compute_assignment_performance([ticket])
    assert metrics["avg_time_to_first_action_hours"] == 1.0


def test_problem_insights_prefers_persisted_problem_link() -> None:
    now = dt.datetime(2026, 2, 15, 12, 0, tzinfo=dt.timezone.utc)
    t1 = _ticket(
        ticket_id="TW-1",
        status=TicketStatus.open,
        created_at=now - dt.timedelta(hours=3),
        updated_at=now - dt.timedelta(hours=2),
        problem_id="PB-0002",
    )
    t2 = _ticket(
        ticket_id="TW-2",
        status=TicketStatus.pending,
        created_at=now - dt.timedelta(hours=2),
        updated_at=now - dt.timedelta(hours=1),
        problem_id="PB-0002",
    )
    t1.title = "VPN timeout in Tunis"
    t2.title = "Cannot print from floor 3"

    insights = compute_problem_insights([t1, t2], min_repetitions=2, limit=6)

    assert insights
    assert insights[0]["problem_id"] == "PB-0002"
    assert insights[0]["occurrences"] == 2
