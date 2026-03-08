"""add ai solution feedback loop table

Revision ID: 0026_add_ai_solution_feedback
Revises: 0025_notif_email_prefs_debug
Create Date: 2026-03-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0026_add_ai_solution_feedback"
down_revision = "0025_notif_email_prefs_debug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_solution_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("vote", sa.String(length=16), nullable=False),
        sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_ai_solution_feedback_source_source_id", "ai_solution_feedback", ["source", "source_id"])
    op.create_index("ix_ai_solution_feedback_user_id", "ai_solution_feedback", ["user_id"])
    op.create_index("ix_ai_solution_feedback_created_at", "ai_solution_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_solution_feedback_created_at", table_name="ai_solution_feedback")
    op.drop_index("ix_ai_solution_feedback_user_id", table_name="ai_solution_feedback")
    op.drop_index("ix_ai_solution_feedback_source_source_id", table_name="ai_solution_feedback")
    op.drop_table("ai_solution_feedback")
