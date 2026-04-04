"""normalize notification events, routing prefs, and dedupe fields

Revision ID: 0030_notification_event_routing
Revises: 0029_add_ticket_due_at
Create Date: 2026-03-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030_notification_event_routing"
down_revision = "0029_add_ticket_due_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("event_type", sa.String(length=48), nullable=False, server_default="system_alert"),
    )
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("pinned_until_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_notifications_user_id_event_type", "notifications", ["user_id", "event_type"])

    op.add_column(
        "notification_preferences",
        sa.Column("immediate_email_min_severity", sa.String(length=16), nullable=False, server_default="high"),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("critical_bypass_quiet_hours", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("ticket_assignment_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("ticket_comment_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("sla_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("problem_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("ai_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "ai_notifications_enabled")
    op.drop_column("notification_preferences", "problem_notifications_enabled")
    op.drop_column("notification_preferences", "sla_notifications_enabled")
    op.drop_column("notification_preferences", "ticket_comment_enabled")
    op.drop_column("notification_preferences", "ticket_assignment_enabled")
    op.drop_column("notification_preferences", "critical_bypass_quiet_hours")
    op.drop_column("notification_preferences", "quiet_hours_enabled")
    op.drop_column("notification_preferences", "digest_enabled")
    op.drop_column("notification_preferences", "immediate_email_min_severity")

    op.drop_index("ix_notifications_user_id_event_type", table_name="notifications")
    op.drop_column("notifications", "pinned_until_read")
    op.drop_column("notifications", "dedupe_key")
    op.drop_column("notifications", "event_type")
