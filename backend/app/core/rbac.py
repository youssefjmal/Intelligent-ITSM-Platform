"""Centralized RBAC policy and ticket scope helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.enums import UserRole
from app.models.ticket import Ticket
from app.models.user import User

Permission = str

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
    UserRole.viewer: {
        "view_dashboard",
        "view_tickets",
        "view_recommendations",
        "view_analytics",
        "use_chat",
    },
}


def has_permission(user: User, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def is_agent(user: User) -> bool:
    return user.role == UserRole.agent


def _matches_user_identity(value: str | None, user: User) -> bool:
    target = (value or "").strip().lower()
    if not target:
        return False
    return target in {(user.name or "").strip().lower(), (user.email or "").strip().lower()}


def can_view_ticket(user: User, ticket: Ticket) -> bool:
    if user.role in {UserRole.admin, UserRole.agent}:
        return True
    if getattr(ticket, "reporter_id", None) and str(ticket.reporter_id) == str(user.id):
        return True
    if ticket.reporter and _matches_user_identity(ticket.reporter, user):
        return True
    if user.role == UserRole.viewer:
        if _matches_user_identity(ticket.assignee, user):
            return True
        for comment in ticket.comments or []:
            if _matches_user_identity(getattr(comment, "author", None), user):
                return True
    return False


def can_comment_ticket(user: User, ticket: Ticket) -> bool:
    if user.role in {UserRole.admin, UserRole.agent, UserRole.user}:
        return can_view_ticket(user, ticket)
    return False


def can_resolve_ticket(user: User, ticket: Ticket) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.role == UserRole.agent:
        return True
    return False


def can_edit_ticket_triage(user: User, ticket: Ticket) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.role == UserRole.agent:
        # Agents can reassign/retag queue tickets and their own assigned tickets.
        return not ticket.assignee or _matches_user_identity(ticket.assignee, user)
    return False


def filter_tickets_for_user(user: User, tickets: Iterable[Ticket]) -> list[Ticket]:
    if user.role in {UserRole.admin, UserRole.agent}:
        return list(tickets)
    return [ticket for ticket in tickets if can_view_ticket(user, ticket)]
