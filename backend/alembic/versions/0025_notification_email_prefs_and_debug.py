"""add notification preference, delivery events, and rich payload columns

Revision ID: 0025_notif_email_prefs_debug
Revises: 0024_add_sla_at_risk_value
Create Date: 2026-03-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_notif_email_prefs_debug"
down_revision = "0024_add_sla_at_risk_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("notifications", sa.Column("action_type", sa.String(length=24), nullable=True))
    op.add_column("notifications", sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_min_severity", sa.String(length=16), nullable=False, server_default="critical"),
        sa.Column("digest_frequency", sa.String(length=24), nullable=False, server_default="hourly"),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "notification_delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_name", sa.String(length=120), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("recipients_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duplicate_suppression", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=False, server_default="in-app"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_notification_delivery_events_notification_id", "notification_delivery_events", ["notification_id"])
    op.create_index("ix_notification_delivery_events_created_at", "notification_delivery_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_delivery_events_created_at", table_name="notification_delivery_events")
    op.drop_index("ix_notification_delivery_events_notification_id", table_name="notification_delivery_events")
    op.drop_table("notification_delivery_events")
    op.drop_table("notification_preferences")
    op.drop_column("notifications", "action_payload")
    op.drop_column("notifications", "action_type")
    op.drop_column("notifications", "metadata_json")
