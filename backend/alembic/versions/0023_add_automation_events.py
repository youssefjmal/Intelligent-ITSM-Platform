"""add automation events

Revision ID: 0023_add_automation_events
Revises: 0022_add_ai_sla_risk_evaluations
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_add_automation_events"
down_revision = "0022_add_ai_sla_risk_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_events_ticket_id", "automation_events", ["ticket_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_automation_events_ticket_id", table_name="automation_events")
    op.drop_table("automation_events")
