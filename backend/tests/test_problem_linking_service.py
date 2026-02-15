from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from app.models.enums import TicketCategory, TicketStatus
from app.services import problems


class _Query:
    def __init__(self, *, first_item=None, rows=None):  # noqa: ANN001
        self._first_item = first_item
        self._rows = list(rows or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._first_item

    def all(self):  # noqa: ANN201
        return list(self._rows)


class _FakeDb:
    def __init__(self, *, problem=None, tickets=None):  # noqa: ANN001
        self.problem = problem
        self.tickets = list(tickets or [])
        self.added = []

    def query(self, model):  # noqa: ANN001
        if model is problems.Problem:
            rows = [self.problem] if self.problem is not None else []
            return _Query(first_item=self.problem, rows=rows)
        if model is problems.Ticket:
            return _Query(rows=self.tickets)
        return _Query()

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def flush(self) -> None:
        return None


def test_similarity_key_normalizes_accents_spacing_and_ids() -> None:
    key_a = problems.compute_similarity_key(
        "[TW-2002] Réseau   VPN !!! timeout ",
        TicketCategory.network,
        description="Les utilisateurs ne se connectent plus.",
        tags=["vpn", "network"],
    )
    key_b = problems.compute_similarity_key(
        "reseau vpn timeout",
        TicketCategory.network,
        description="connexion impossible pour les utilisateurs",
        tags=["network", "vpn"],
    )
    assert key_a == key_b
    assert key_a.startswith("network|")


def test_recompute_problem_stats_is_idempotent() -> None:
    now = dt.datetime(2026, 2, 15, 12, 0, tzinfo=dt.timezone.utc)
    problem = SimpleNamespace(
        id="PB-0002",
        occurrences_count=0,
        active_count=0,
        last_seen_at=None,
        updated_at=now,
    )
    tickets = [
        SimpleNamespace(
            id="TW-1",
            problem_id="PB-0002",
            status=TicketStatus.open,
            created_at=now - dt.timedelta(hours=2),
            jira_created_at=None,
        ),
        SimpleNamespace(
            id="TW-2",
            problem_id="PB-0002",
            status=TicketStatus.resolved,
            created_at=now - dt.timedelta(hours=1),
            jira_created_at=None,
        ),
    ]
    db = _FakeDb(problem=problem, tickets=tickets)

    problems.recompute_problem_stats(db, "PB-0002")
    first = (problem.occurrences_count, problem.active_count, problem.last_seen_at)
    problems.recompute_problem_stats(db, "PB-0002")
    second = (problem.occurrences_count, problem.active_count, problem.last_seen_at)

    assert first == second
    assert first[0] == 2
    assert first[1] == 1


def test_link_ticket_to_problem_defers_creation_before_threshold(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-9999",
        title="VPN timeout agence Tunis",
        description="Users cannot connect",
        category=TicketCategory.network,
        tags=["vpn", "network"],
        problem_id=None,
    )
    monkeypatch.setattr(problems, "_find_similar_problem", lambda *args, **kwargs: None)
    monkeypatch.setattr(problems, "_recent_similar_tickets", lambda *args, **kwargs: [ticket])

    fake_db = _FakeDb()
    linked = problems.link_ticket_to_problem(fake_db, ticket)

    assert linked is None
    assert ticket.problem_id is None


def test_link_ticket_to_problem_links_existing_problem(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id="TW-9999",
        title="VPN timeout agence Tunis",
        description="Users cannot connect",
        category=TicketCategory.network,
        tags=["vpn", "network"],
        problem_id=None,
    )
    target_problem = SimpleNamespace(id="PB-0002")
    touched: list[str] = []

    monkeypatch.setattr(problems, "_find_similar_problem", lambda *args, **kwargs: target_problem)
    monkeypatch.setattr(problems, "recompute_problem_stats", lambda _db, pid: touched.append(pid))

    fake_db = _FakeDb()
    problems.link_ticket_to_problem(fake_db, ticket)
    problems.link_ticket_to_problem(fake_db, ticket)

    assert ticket.problem_id == "PB-0002"
    assert touched == ["PB-0002", "PB-0002"]
