"""add knowledge_drafts table

Revision ID: 0040_add_knowledge_drafts
Revises: 0039_add_chat_message_metadata
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040_add_knowledge_drafts"
down_revision = "0039_add_chat_message_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("symptoms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("workaround", sa.Text, nullable=True),
        sa.Column("resolution_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_note", sa.Text, nullable=False, server_default=""),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("source", sa.String(32), nullable=False, server_default="llm"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jira_issue_key", sa.String(64), nullable=True),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_knowledge_drafts_ticket_id", "knowledge_drafts", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_drafts_ticket_id", table_name="knowledge_drafts")
    op.drop_table("knowledge_drafts")
