"""Ticket and comment models for ITSM workflows."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import TicketCategory, TicketPriority, TicketStatus


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("external_source", "external_id", name="uq_tickets_external_source_external_id"),
        UniqueConstraint("jira_key", name="uq_tickets_jira_key"),
        UniqueConstraint("jira_issue_id", name="uq_tickets_jira_issue_id"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", values_callable=lambda x: [e.value for e in x]),
        default=TicketStatus.open,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        Enum(TicketPriority, name="ticket_priority", values_callable=lambda x: [e.value for e in x]),
        default=TicketPriority.medium,
    )
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category", values_callable=lambda x: [e.value for e in x]),
        default=TicketCategory.service_request,
    )
    assignee: Mapped[str] = mapped_column(String(255), nullable=False)
    reporter: Mapped[str] = mapped_column(String(255), nullable=False)
    reporter_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    problem_id: Mapped[str | None] = mapped_column(ForeignKey("problems.id", ondelete="SET NULL"), nullable=True, index=True)
    auto_assignment_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_priority_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    assignment_model_version: Mapped[str] = mapped_column(String(40), default="legacy", nullable=False)
    priority_model_version: Mapped[str] = mapped_column(String(40), default="legacy", nullable=False)
    predicted_priority: Mapped[TicketPriority | None] = mapped_column(
        Enum(TicketPriority, name="ticket_priority", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    predicted_category: Mapped[TicketCategory | None] = mapped_column(
        Enum(TicketCategory, name="ticket_category", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    assignment_change_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_action_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    source: Mapped[str] = mapped_column(String(32), default="local", nullable=False, index=True)
    jira_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    jira_issue_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    jira_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    external_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    jira_sla_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Local SLA status values: ok, at_risk, breached, paused, completed, unknown.
    sla_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sla_first_response_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_resolution_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_first_response_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sla_resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sla_first_response_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_resolution_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_remaining_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_elapsed_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority_auto_escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority_escalation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority_escalated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    comments: Mapped[list[TicketComment]] = relationship(
        "TicketComment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketComment.created_at",
    )
    problem = relationship("Problem", back_populates="tickets")


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    __table_args__ = (
        UniqueConstraint("ticket_id", "external_comment_id", name="uq_ticket_comments_ticket_external_comment"),
        UniqueConstraint("jira_comment_id", name="uq_ticket_comments_jira_comment_id"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    jira_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_comment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    external_source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    external_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="comments")
