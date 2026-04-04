"""add ticket due date field

Revision ID: 0029_add_ticket_due_at
Revises: 0028_ticket_type_rebal
Create Date: 2026-03-14 03:35:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_add_ticket_due_at"
down_revision = "0028_ticket_type_rebal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE tickets
        SET due_at = COALESCE(sla_resolution_due_at, sla_first_response_due_at)
        WHERE due_at IS NULL
          AND COALESCE(sla_resolution_due_at, sla_first_response_due_at) IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("tickets", "due_at")
