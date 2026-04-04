"""Add ai_classification_logs table.

Stores every AI classification decision — priority, category, ticket_type,
confidence, decision source (llm/semantic/fallback) — for auditability and
governance reporting.

Revision ID: 0034_add_ai_classification_logs
Revises: 0033_add_ticket_summary
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_add_ai_classification_logs"
down_revision = "0033_add_ticket_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_classification_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.String(64), nullable=True),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("description_snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_priority", sa.String(16), nullable=True),
        sa.Column("suggested_category", sa.String(32), nullable=True),
        sa.Column("suggested_ticket_type", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confidence_band", sa.String(16), nullable=True),
        sa.Column("decision_source", sa.String(16), nullable=False, server_default="llm"),
        sa.Column("strong_match_count", sa.Integer(), nullable=True),
        sa.Column("recommendation_mode", sa.String(32), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_version", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_classification_logs_ticket_id",
        "ai_classification_logs",
        ["ticket_id"],
    )
    op.create_index(
        "ix_ai_classification_logs_created_at",
        "ai_classification_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_classification_logs_created_at", table_name="ai_classification_logs")
    op.drop_index("ix_ai_classification_logs_ticket_id", table_name="ai_classification_logs")
    op.drop_table("ai_classification_logs")
