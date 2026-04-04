"""Add index on ai_solution_feedback.vote for legacy analytics compatibility.

``vote`` is deprecated in favour of ``feedback_type`` but is still targeted by
existing analytics endpoints and queries.  Without an index, every lookup on
``vote`` performs a full sequential scan of the feedback table, which degrades
as the table grows.

This migration adds a simple B-tree index so that legacy queries remain
efficient while the deprecation is in progress.

Removal: drop this index (and the vote column) once all analytics consumers
have been migrated to use ``feedback_type`` instead and the column is formally
removed from the model.

Revision ID: 0032_add_feedback_vote_index
Revises: 0031_expand_ai_feedback_loop
Create Date: 2026-03-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0032_add_feedback_vote_index"
down_revision = "0031_expand_ai_feedback_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added to support legacy analytics queries while the vote column is
    # deprecated.  Remove this index when the vote column is removed.
    op.create_index(
        "ix_ai_solution_feedback_vote",
        "ai_solution_feedback",
        ["vote"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_solution_feedback_vote", table_name="ai_solution_feedback")
