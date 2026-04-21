"""Centralized RBAC policy and ticket scope helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.enums import UserRole
from app.models.ticket import Ticket
from app.models.user import User

Permission = str
CUSTOMER_ALLOWED_STATUS_VALUES = {"open", "resolved", "closed"}


def effective_role(role: UserRole) -> UserRole:
    """Collapse deprecated role aliases into the active product role model."""
    if role == UserRole.viewer:
        return UserRole.user
    return role

ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.admin: {
        "view_dashboard",
        "view_tickets",
        "create_ticket",
        "comment_ticket",
        "resolve_ticket",
        "reassign_ticket",
        "edit_ticket_triage",
        "view_recommendations",
        "view_analytics",
        "manage_users",
        "view_email_logs",
        "configure_integrations",
        "view_admin",
        "use_chat",
    },
    UserRole.agent: {
        "view_dashboard",
        "view_tickets",
        "create_ticket",
        "comment_ticket",
        "resolve_ticket",
        "reassign_ticket",
        "edit_ticket_triage",
        "view_recommendations",
        "view_analytics",
        "use_chat",
    },
    UserRole.user: {
        "view_dashboard",
        "view_tickets",
        "create_ticket",
        "comment_ticket",
        "view_recommendations",
        "view_analytics",
        "use_chat",
    },
    # Legacy compatibility only. Viewer is treated as a customer/user alias.
    UserRole.viewer: set(),
}


def has_permission(user: User, permission: Permission) -> bool:
    role = effective_role(user.role)
    return permission in ROLE_PERMISSIONS.get(role, set())


def is_admin(user: User) -> bool:
    return effective_role(user.role) == UserRole.admin


def is_agent(user: User) -> bool:
    return effective_role(user.role) == UserRole.agent


def _matches_user_identity(value: str | None, user: User) -> bool:
    target = (value or "").strip().lower()
    if not target:
        return False
    return target in {(user.name or "").strip().lower(), (user.email or "").strip().lower()}


def is_ticket_requester(user: User, ticket: Ticket) -> bool:
    if getattr(ticket, "reporter_id", None) and str(ticket.reporter_id) == str(user.id):
        return True
    return bool(ticket.reporter and _matches_user_identity(ticket.reporter, user))


def can_view_ticket(user: User, ticket: Ticket) -> bool:
    role = effective_role(user.role)
    if role in {UserRole.admin, UserRole.agent}:
        return True
    return is_ticket_requester(user, ticket)


def can_comment_ticket(user: User, ticket: Ticket) -> bool:
    role = effective_role(user.role)
    if role in {UserRole.admin, UserRole.agent, UserRole.user}:
        return can_view_ticket(user, ticket)
    return False


def can_resolve_ticket(user: User, ticket: Ticket) -> bool:
    role = effective_role(user.role)
    if role == UserRole.admin:
        return True
    if role == UserRole.agent:
        return True
    return False


def can_update_ticket_status(
    user: User,
    ticket: Ticket,
    *,
    new_status: str,
    has_comment: bool = False,
) -> bool:
    role = effective_role(user.role)
    if role in {UserRole.admin, UserRole.agent}:
        return True
    if role != UserRole.user or not is_ticket_requester(user, ticket):
        return False
    normalized_status = str(new_status or "").strip().lower()
    current_status = str(getattr(ticket.status, "value", ticket.status) or "").strip().lower()
    if has_comment and normalized_status == current_status:
        return True
    return normalized_status in CUSTOMER_ALLOWED_STATUS_VALUES


def can_edit_ticket_triage(user: User, ticket: Ticket) -> bool:
    role = effective_role(user.role)
    if role == UserRole.admin:
        return True
    if role == UserRole.agent:
        # Agents can reassign/retag queue tickets and their own assigned tickets.
        return not ticket.assignee or _matches_user_identity(ticket.assignee, user)
    return False


def filter_tickets_for_user(user: User, tickets: Iterable[Ticket]) -> list[Ticket]:
    if effective_role(user.role) in {UserRole.admin, UserRole.agent}:
        return list(tickets)
    return [ticket for ticket in tickets if can_view_ticket(user, ticket)]
