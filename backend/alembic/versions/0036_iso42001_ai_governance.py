"""ISO 42001 AI governance — human oversight columns on ai_classification_logs.

Changes
-------
ai_classification_logs table:
  - human_reviewed_at  TIMESTAMPTZ  NULL  — timestamp when a human reviewed this decision
  - override_reason    TEXT         NULL  — free-text reason if the AI decision was overridden

These fields support ISO 42001 clause 6.1 (risk treatment) and clause 9.1 (monitoring)
by creating a verifiable trail of human oversight over AI classification decisions.

Revision ID: 0036_iso42001_ai_governance
Revises: 0035_security_hardening
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_iso42001_ai_governance"
down_revision = "0035_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_classification_logs",
        sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_classification_logs",
        sa.Column("override_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_ai_classification_logs_human_reviewed_at",
        "ai_classification_logs",
        ["human_reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_classification_logs_human_reviewed_at", table_name="ai_classification_logs")
    op.drop_column("ai_classification_logs", "override_reason")
    op.drop_column("ai_classification_logs", "human_reviewed_at")
