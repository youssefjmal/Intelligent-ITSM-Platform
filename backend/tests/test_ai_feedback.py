from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.ai import AIFeedbackRequest
from app.services.ai import feedback as feedback_service


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class _FakeDB:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        self.refreshed.append(obj)


class _FakeQuery:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = list(rows)

    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeAnalyticsDB:
    def __init__(self, rows) -> None:  # noqa: ANN001
        self._rows = list(rows)

    def query(self, *args, **kwargs):  # noqa: ANN001
        return _FakeQuery(self._rows)


class _FailingQueryDB:
    def __init__(self) -> None:
        self.rollbacks = 0

    def query(self, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError("undefined_column")

    def rollback(self) -> None:
        self.rollbacks += 1


def test_upsert_agent_feedback_creates_new_row(monkeypatch) -> None:
    db = _FakeDB()
    monkeypatch.setattr(feedback_service, "_find_existing_agent_feedback", lambda *args, **kwargs: None)

    row = feedback_service.upsert_agent_feedback(
        db,
        user_id=uuid4(),
        feedback_type="useful",
        source_surface="ticket_detail",
        ticket_id="TW-101",
        recommended_action="Refresh the VPN policy session.",
        display_mode="evidence_action",
        confidence=0.72,
        reasoning="A resolved ticket used the same action.",
        match_summary="Matched on vpn, policy, session",
        evidence_count=2,
        metadata={"source_label": "resolved_ticket_grounded"},
    )

    assert row.ticket_id == "TW-101"
    assert row.feedback_type == "useful"
    assert row.source_surface == "ticket_detail"
    assert row.target_key == "ticket:TW-101"
    assert row.recommended_action_snapshot == "Refresh the VPN policy session."
    assert row.display_mode_snapshot == "evidence_action"
    assert row.confidence_snapshot == 0.72
    assert row.match_summary_snapshot == "Matched on vpn, policy, session"
    assert row.evidence_count_snapshot == 2
    assert row.context_json == {"source_label": "resolved_ticket_grounded"}
    assert db.commits == 1
    assert len(db.added) == 1


def test_upsert_agent_feedback_updates_existing_row(monkeypatch) -> None:
    db = _FakeDB()
    existing = SimpleNamespace(
        user_id=uuid4(),
        ticket_id="TW-202",
        recommendation_id=None,
        recommendation_text="Old action",
        source="ticket_detail",
        source_id="TW-202",
        vote="rejected",
        feedback_type="rejected",
        source_surface="ticket_detail",
        target_key="ticket:TW-202",
        recommended_action_snapshot="Old action",
        display_mode_snapshot="tentative_diagnostic",
        confidence_snapshot=0.31,
        reasoning_snapshot="Old reasoning",
        match_summary_snapshot="old overlap",
        evidence_count_snapshot=1,
        context_json={"source_label": "fallback_rules"},
        created_at=_now(),
        updated_at=_now(),
    )
    monkeypatch.setattr(feedback_service, "_find_existing_agent_feedback", lambda *args, **kwargs: existing)

    row = feedback_service.upsert_agent_feedback(
        db,
        user_id=existing.user_id,
        feedback_type="applied",
        source_surface="ticket_detail",
        ticket_id="TW-202",
        recommended_action="Restart the sync worker after token refresh.",
        display_mode="evidence_action",
        confidence=0.81,
        reasoning="A resolved CRM token incident used this step.",
        match_summary="Matched on crm, token, worker",
        evidence_count=3,
        metadata={"source_label": "resolved_ticket_grounded"},
    )

    assert row is existing
    assert row.feedback_type == "applied"
    assert row.vote == "applied"
    assert row.recommended_action_snapshot == "Restart the sync worker after token refresh."
    assert row.confidence_snapshot == 0.81
    assert row.context_json == {"source_label": "resolved_ticket_grounded"}
    assert db.added == []
    assert db.commits == 1


def test_summarize_feedback_rows_computes_counts_rates_and_current_feedback() -> None:
    current_user_id = uuid4()
    earlier = _now() - dt.timedelta(minutes=5)
    later = _now()
    rows = [
        SimpleNamespace(feedback_type="useful", user_id=current_user_id, created_at=earlier, updated_at=earlier),
        SimpleNamespace(feedback_type="applied", user_id=current_user_id, created_at=later, updated_at=later),
        SimpleNamespace(feedback_type="rejected", user_id=uuid4(), created_at=later, updated_at=later),
        SimpleNamespace(feedback_type="not_relevant", user_id=uuid4(), created_at=later, updated_at=later),
    ]

    bundle = feedback_service._summarize_feedback_rows(rows, current_user_id=current_user_id)

    assert bundle["current_feedback"]["feedback_type"] == "applied"
    assert bundle["feedback_summary"]["total_feedback"] == 4
    assert bundle["feedback_summary"]["useful_count"] == 1
    assert bundle["feedback_summary"]["applied_count"] == 1
    assert bundle["feedback_summary"]["rejected_count"] == 1
    assert bundle["feedback_summary"]["not_relevant_count"] == 1
    assert bundle["feedback_summary"]["usefulness_rate"] == 0.25
    assert bundle["feedback_summary"]["applied_rate"] == 0.25
    assert bundle["feedback_summary"]["rejection_rate"] == 0.25


def test_ai_feedback_request_rejects_invalid_feedback_type() -> None:
    with pytest.raises(ValidationError):
        AIFeedbackRequest(
            ticket_id="TW-909",
            source_surface="ticket_detail",
            feedback_type="great",
            recommended_action="Restart the worker.",
        )


def test_aggregate_agent_feedback_analytics_groups_by_surface() -> None:
    now = _now()
    db = _FakeAnalyticsDB(
        [
            SimpleNamespace(
                feedback_type="useful",
                source_surface="ticket_detail",
                display_mode_snapshot="evidence_action",
                confidence_snapshot=0.82,
                context_json={"recommendation_mode": "resolved_ticket_grounded", "source_label": "jira_semantic"},
                user_id=uuid4(),
                created_at=now,
                updated_at=now,
            ),
            SimpleNamespace(
                feedback_type="applied",
                source_surface="ticket_detail",
                display_mode_snapshot="tentative_diagnostic",
                confidence_snapshot=0.58,
                context_json={"recommendation_mode": "fallback_diagnostic", "source_label": "fallback_rules"},
                user_id=uuid4(),
                created_at=now,
                updated_at=now,
            ),
            SimpleNamespace(
                feedback_type="rejected",
                source_surface="recommendations_page",
                display_mode_snapshot="no_strong_match",
                confidence_snapshot=0.24,
                context_json={"recommendation_mode": "fallback_diagnostic", "source_label": "fallback_rules"},
                user_id=uuid4(),
                created_at=now,
                updated_at=now,
            ),
        ]
    )

    payload = feedback_service.aggregate_agent_feedback_analytics(db)

    assert payload["total_feedback"] == 3
    assert payload["useful_count"] == 1
    assert payload["applied_count"] == 1
    assert payload["rejected_count"] == 1
    assert payload["by_surface"]["ticket_detail"]["total_feedback"] == 2
    assert payload["by_surface"]["recommendations_page"]["rejected_count"] == 1
    assert payload["by_display_mode"]["evidence_action"]["useful_count"] == 1
    assert payload["by_confidence_band"]["high"]["total_feedback"] == 1
    assert payload["by_recommendation_mode"]["fallback_diagnostic"]["total_feedback"] == 2
    assert payload["by_source_label"]["fallback_rules"]["total_feedback"] == 2


def test_get_feedback_bundle_returns_empty_summary_when_query_fails() -> None:
    db = _FailingQueryDB()

    payload = feedback_service.get_feedback_bundle_for_target(
        db,
        current_user_id="agent-1",
        source_surface="ticket_detail",
        ticket_id="TW-404",
    )

    assert payload["current_feedback"] is None
    assert payload["feedback_summary"]["total_feedback"] == 0
    assert db.rollbacks == 1


def test_aggregate_feedback_for_sources_returns_empty_map_when_query_fails() -> None:
    db = _FailingQueryDB()

    payload = feedback_service.aggregate_feedback_for_sources(
        db,
        source="jira_comment",
        source_ids=["TW-100", "TW-101"],
    )

    assert payload == {}
    assert db.rollbacks == 1
