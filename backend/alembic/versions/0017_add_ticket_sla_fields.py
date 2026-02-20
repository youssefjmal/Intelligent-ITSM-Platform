"""add ticket sla state fields and auto escalation metadata

Revision ID: 0017_add_ticket_sla_fields
Revises: 0016_add_kb_chunks_pgvector
Create Date: 2026-02-18 00:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0017_add_ticket_sla_fields"
down_revision = "0016_add_kb_chunks_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("jira_sla_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("tickets", sa.Column("sla_status", sa.String(length=32), nullable=True))
    op.add_column("tickets", sa.Column("sla_first_response_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("sla_resolution_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tickets",
        sa.Column(
            "sla_first_response_breached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "sla_resolution_breached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("tickets", sa.Column("sla_first_response_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("sla_resolution_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("sla_remaining_minutes", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("sla_elapsed_minutes", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("sla_last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tickets",
        sa.Column(
            "priority_auto_escalated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("tickets", sa.Column("priority_escalation_reason", sa.String(length=255), nullable=True))
    op.add_column("tickets", sa.Column("priority_escalated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "priority_escalated_at")
    op.drop_column("tickets", "priority_escalation_reason")
    op.drop_column("tickets", "priority_auto_escalated")
    op.drop_column("tickets", "sla_last_synced_at")
    op.drop_column("tickets", "sla_elapsed_minutes")
    op.drop_column("tickets", "sla_remaining_minutes")
    op.drop_column("tickets", "sla_resolution_completed_at")
    op.drop_column("tickets", "sla_first_response_completed_at")
    op.drop_column("tickets", "sla_resolution_breached")
    op.drop_column("tickets", "sla_first_response_breached")
    op.drop_column("tickets", "sla_resolution_due_at")
    op.drop_column("tickets", "sla_first_response_due_at")
    op.drop_column("tickets", "sla_status")
    op.drop_column("tickets", "jira_sla_payload")

