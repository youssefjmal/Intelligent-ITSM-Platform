"""add ai sla risk evaluations

Revision ID: 0022_add_ai_sla_risk_evaluations
Revises: 0021_add_notifications
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_add_ai_sla_risk_evaluations"
down_revision = "0021_add_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_sla_risk_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", sa.String(length=20), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("suggested_priority", sa.String(length=16), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("decision_source", sa.String(length=16), nullable=False, server_default="shadow"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_sla_risk_evaluations_ticket_id",
        "ai_sla_risk_evaluations",
        ["ticket_id"],
        unique=False,
    )
    op.execute("ALTER TABLE ai_sla_risk_evaluations ALTER COLUMN decision_source DROP DEFAULT")


def downgrade() -> None:
    op.drop_index("ix_ai_sla_risk_evaluations_ticket_id", table_name="ai_sla_risk_evaluations")
    op.drop_table("ai_sla_risk_evaluations")
