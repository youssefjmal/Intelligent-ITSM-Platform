"""add jira-native waiting statuses to ticket_status enum

Revision ID: 0020_add_jira_native_waiting_statuses
Revises: 0019_kb_chunk_identity_uniques
Create Date: 2026-02-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0020_add_jira_native_waiting_statuses"
down_revision = "0019_kb_chunk_identity_uniques"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'waiting-for-customer'")
        op.execute("ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'waiting-for-support-vendor'")
    # Normalize legacy pending rows to Jira-native waiting state.
    op.execute(
        """
        UPDATE tickets
        SET status = 'waiting-for-support-vendor'
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    # Keep enum values in place; map rows back to legacy value.
    op.execute(
        """
        UPDATE tickets
        SET status = 'pending'
        WHERE status IN ('waiting-for-customer', 'waiting-for-support-vendor')
        """
    )
