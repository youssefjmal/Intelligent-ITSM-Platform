"""expand ai feedback loop for recommendation surfaces

Revision ID: 0031_expand_ai_feedback_loop
Revises: 0030_notification_event_routing
Create Date: 2026-03-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031_expand_ai_feedback_loop"
down_revision = "0030_notification_event_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_solution_feedback", sa.Column("ticket_id", sa.String(length=20), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("recommendation_id", sa.String(length=64), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("feedback_type", sa.String(length=24), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("source_surface", sa.String(length=32), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("target_key", sa.String(length=128), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("recommended_action_snapshot", sa.Text(), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("display_mode_snapshot", sa.String(length=32), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("confidence_snapshot", sa.Float(), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("reasoning_snapshot", sa.Text(), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("match_summary_snapshot", sa.Text(), nullable=True))
    op.add_column("ai_solution_feedback", sa.Column("evidence_count_snapshot", sa.Integer(), nullable=True))
    op.add_column(
        "ai_solution_feedback",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_foreign_key(
        "fk_ai_solution_feedback_ticket_id",
        "ai_solution_feedback",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_solution_feedback_target_lookup",
        "ai_solution_feedback",
        ["user_id", "source_surface", "target_key"],
    )
    op.create_index(
        "ix_ai_solution_feedback_ticket_surface",
        "ai_solution_feedback",
        ["ticket_id", "source_surface"],
    )
    op.create_index(
        "ix_ai_solution_feedback_recommendation_surface",
        "ai_solution_feedback",
        ["recommendation_id", "source_surface"],
    )
    op.create_index(
        "ix_ai_solution_feedback_feedback_type",
        "ai_solution_feedback",
        ["feedback_type"],
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_solution_feedback
            SET
              feedback_type = COALESCE(feedback_type, vote),
              source_surface = COALESCE(source_surface, 'ticket_chatbot'),
              updated_at = COALESCE(updated_at, created_at)
            """
        )
    )
    op.alter_column("ai_solution_feedback", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_ai_solution_feedback_feedback_type", table_name="ai_solution_feedback")
    op.drop_index("ix_ai_solution_feedback_recommendation_surface", table_name="ai_solution_feedback")
    op.drop_index("ix_ai_solution_feedback_ticket_surface", table_name="ai_solution_feedback")
    op.drop_index("ix_ai_solution_feedback_target_lookup", table_name="ai_solution_feedback")
    op.drop_constraint("fk_ai_solution_feedback_ticket_id", "ai_solution_feedback", type_="foreignkey")
    op.drop_column("ai_solution_feedback", "updated_at")
    op.drop_column("ai_solution_feedback", "evidence_count_snapshot")
    op.drop_column("ai_solution_feedback", "match_summary_snapshot")
    op.drop_column("ai_solution_feedback", "reasoning_snapshot")
    op.drop_column("ai_solution_feedback", "confidence_snapshot")
    op.drop_column("ai_solution_feedback", "display_mode_snapshot")
    op.drop_column("ai_solution_feedback", "recommended_action_snapshot")
    op.drop_column("ai_solution_feedback", "target_key")
    op.drop_column("ai_solution_feedback", "source_surface")
    op.drop_column("ai_solution_feedback", "feedback_type")
    op.drop_column("ai_solution_feedback", "recommendation_id")
    op.drop_column("ai_solution_feedback", "ticket_id")
