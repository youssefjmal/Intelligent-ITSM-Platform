from __future__ import annotations

from app.core.rbac import can_edit_ticket_triage, can_resolve_ticket, can_view_ticket, has_permission
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, UserRole
from app.models.ticket import Ticket, TicketComment
from app.models.user import User


def _make_user(role: UserRole, *, name: str, email: str) -> User:
    return User(name=name, email=email, role=role)


def _make_ticket(*, reporter: str, assignee: str = "Agent A") -> Ticket:
    return Ticket(
        id="TW-9999",
        title="Sample",
        description="Sample ticket",
        status=TicketStatus.open,
        priority=TicketPriority.medium,
        category=TicketCategory.service_request,
        assignee=assignee,
        reporter=reporter,
    )


def test_rbac_permissions_matrix_smoke() -> None:
    admin = _make_user(UserRole.admin, name="Admin", email="admin@example.com")
    agent = _make_user(UserRole.agent, name="Agent", email="agent@example.com")
    requester = _make_user(UserRole.user, name="Requester", email="requester@example.com")
    viewer = _make_user(UserRole.viewer, name="Viewer", email="viewer@example.com")

    assert has_permission(admin, "manage_users")
    assert has_permission(agent, "resolve_ticket")
    assert has_permission(requester, "create_ticket")
    assert not has_permission(viewer, "resolve_ticket")


def test_user_scope_can_only_view_own_reported_tickets() -> None:
    requester = _make_user(UserRole.user, name="Requester", email="requester@example.com")
    own = _make_ticket(reporter="Requester")
    other = _make_ticket(reporter="Another User")

    assert can_view_ticket(requester, own)
    assert not can_view_ticket(requester, other)


def test_viewer_can_view_participating_ticket_but_cannot_edit() -> None:
    viewer = _make_user(UserRole.viewer, name="Viewer", email="viewer@example.com")
    ticket = _make_ticket(reporter="Another User")
    ticket.comments = [
        TicketComment(id="c1", ticket_id=ticket.id, author="Viewer", content="I saw this"),
    ]

    assert can_view_ticket(viewer, ticket)
    assert not can_resolve_ticket(viewer, ticket)
    assert not can_edit_ticket_triage(viewer, ticket)
