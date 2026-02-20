"""Shared enum values used by the database models and schemas."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    agent = "agent"
    user = "user"
    viewer = "viewer"


class SeniorityLevel(str, enum.Enum):
    intern = "intern"
    junior = "junior"
    middle = "middle"
    senior = "senior"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in-progress"
    waiting_for_customer = "waiting-for-customer"
    waiting_for_support_vendor = "waiting-for-support-vendor"
    # Legacy status kept for backward compatibility with old payloads.
    pending = "pending"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class TicketCategory(str, enum.Enum):
    infrastructure = "infrastructure"
    network = "network"
    security = "security"
    application = "application"
    service_request = "service_request"
    hardware = "hardware"
    email = "email"
    problem = "problem"


class ProblemStatus(str, enum.Enum):
    open = "open"
    investigating = "investigating"
    known_error = "known_error"
    resolved = "resolved"
    closed = "closed"


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
