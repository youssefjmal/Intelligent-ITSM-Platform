"""add change ticket type and change management fields

Revision ID: 0037_add_change_management
Revises: 0036_iso42001_ai_governance
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_add_change_management"
down_revision = "0036_iso42001_ai_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend the ticket_type enum with "change"
    op.execute("ALTER TYPE ticket_type ADD VALUE IF NOT EXISTS 'change'")

    # 2. Add Change Management fields to tickets table
    op.add_column("tickets", sa.Column("change_risk", sa.String(16), nullable=True))
    op.add_column("tickets", sa.Column("change_scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("change_approved", sa.Boolean(), nullable=True))
    op.add_column("tickets", sa.Column("change_approved_by", sa.String(255), nullable=True))
    op.add_column("tickets", sa.Column("change_approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "change_approved_at")
    op.drop_column("tickets", "change_approved_by")
    op.drop_column("tickets", "change_approved")
    op.drop_column("tickets", "change_scheduled_at")
    op.drop_column("tickets", "change_risk")
    # Note: PostgreSQL does not support removing enum values.
    # To fully revert, recreate the enum without "change".
