"""add at_risk to sla_status

Revision ID: 0024_add_sla_at_risk_value
Revises: 0023_add_automation_events
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0024_add_sla_at_risk_value"
down_revision = "0023_add_automation_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change is required; tickets.sla_status is already a VARCHAR column.
    pass


def downgrade() -> None:
    op.execute("UPDATE tickets SET sla_status = 'ok' WHERE sla_status = 'at_risk'")
