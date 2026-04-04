"""Add AI summary fields to tickets table.

Adds two columns:
- ai_summary: text, nullable. Stores the AI-generated summary.
  Null until the summary is first generated.
- summary_generated_at: timestamp with timezone, nullable.
  Records when the summary was last generated or regenerated.
  Used to determine staleness and trigger regeneration.

Regeneration triggers:
- New comment added to the ticket
- Ticket status changes
- Ticket description updated
- summary_generated_at is null (first load)

Revision ID: 0033_add_ticket_summary
Revises: 0032_add_feedback_vote_index
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_add_ticket_summary"
down_revision = "0032_add_feedback_vote_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column(
        "tickets",
        sa.Column("summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tickets", "summary_generated_at")
    op.drop_column("tickets", "ai_summary")
