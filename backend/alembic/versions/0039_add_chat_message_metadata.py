"""add metadata column to chat_conversation_messages

Revision ID: 0039_add_chat_message_metadata
Revises: 0038_add_chat_conversations
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_add_chat_message_metadata"
down_revision = "0038_add_chat_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_conversation_messages",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_conversation_messages", "metadata")
