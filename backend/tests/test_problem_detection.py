from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketStatus
from app.services import problems


class _QueryChain:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = rows

    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        return self._rows


class _FakeDb:
    def __init__(self, tickets):  # noqa: ANN001
        self._tickets = tickets

    def query(self, _model):  # noqa: ANN001
        return _QueryChain(self._tickets)


def _make_ticket(ticket_id: str, title: str, category: TicketCategory) -> SimpleNamespace:
    now = dt.datetime.now(dt.timezone.utc)
    return SimpleNamespace(
        id=ticket_id,
        title=title,
        description="VPN down on site",
        category=category,
        tags=["vpn", "network"],
        status=TicketStatus.open,
        created_at=now,
        problem_id=None,
    )


def test_compute_similarity_key_is_deterministic() -> None:
    key_a = problems.compute_similarity_key(
        title="VPN outage in Tunis office",
        description="Users cannot connect to VPN gateway",
        category=TicketCategory.network,
        tags=["vpn", "network"],
    )
    key_b = problems.compute_similarity_key(
        title="VPN outage in Tunis office",
        description="Users cannot connect to VPN gateway",
        category=TicketCategory.network,
        tags=["network", "vpn"],
    )
    assert key_a == key_b
    assert key_a.startswith("network|")


def test_compute_similarity_key_groups_same_primary_tag() -> None:
    timeout_key = problems.compute_similarity_key(
        title="Incident VPN timeout agence Tunis",
        description="Timeout d'authentification VPN pour plusieurs utilisateurs.",
        category=TicketCategory.network,
        tags=["vpn", "timeout", "reseau"],
    )
    outage_key = problems.compute_similarity_key(
        title="Recurring network incidents - vpn outage",
        description="Panne VPN intermittente sur le meme site.",
        category=TicketCategory.network,
        tags=["vpn", "reseau", "tunis"],
    )
    assert timeout_key == outage_key
    assert timeout_key == "network|tag:vpn"


def test_detect_problems_threshold_and_rerun_idempotent(monkeypatch) -> None:
    tickets = [
        _make_ticket("TW-9001", "VPN outage site A", TicketCategory.network),
        _make_ticket("TW-9002", "VPN outage site B", TicketCategory.network),
        _make_ticket("TW-9003", "VPN outage site C", TicketCategory.network),
        _make_ticket("TW-9004", "VPN outage site D", TicketCategory.network),
        _make_ticket("TW-9005", "VPN outage site E", TicketCategory.network),
    ]
    db = _FakeDb(tickets)

    seen_keys: set[str] = set()

    def fake_upsert(_db, *, similarity_key, tickets):  # noqa: ANN001
        created = similarity_key not in seen_keys
        if created:
            seen_keys.add(similarity_key)
        for ticket in tickets:
            if ticket.problem_id is None:
                ticket.problem_id = "PB-0001"
        return SimpleNamespace(id="PB-0001"), created, True

    monkeypatch.setattr(problems, "upsert_problem", fake_upsert)

    first = problems.detect_problems(db, window_days=7, min_count=5)
    second = problems.detect_problems(db, window_days=7, min_count=5)

    assert first["processed_groups"] == 1
    assert first["created"] == 1
    assert first["linked"] == 5
    assert second["processed_groups"] == 1
    assert second["created"] == 0
    assert second["linked"] == 0
