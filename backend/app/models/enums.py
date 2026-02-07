"""Shared enum values used by the database models and schemas."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    agent = "agent"
    viewer = "viewer"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in-progress"
    pending = "pending"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class TicketCategory(str, enum.Enum):
    bug = "bug"
    feature = "feature"
    support = "support"
    infrastructure = "infrastructure"
    security = "security"


class EmailKind(str, enum.Enum):
    verification = "verification"
    welcome = "welcome"


class RecommendationType(str, enum.Enum):
    pattern = "pattern"
    priority = "priority"
    solution = "solution"
    workflow = "workflow"


class RecommendationImpact(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"
