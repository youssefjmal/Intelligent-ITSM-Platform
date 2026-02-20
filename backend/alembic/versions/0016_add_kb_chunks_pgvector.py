"""add kb_chunks table with pgvector embeddings

Revision ID: 0016_add_kb_chunks_pgvector
Revises: 0015_jira_native_sync_fields
Create Date: 2026-02-17 00:00:00.000000
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision = "0016_add_kb_chunks_pgvector"
down_revision = "0015_jira_native_sync_fields"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    bind = op.get_bind()
    has_vector = bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
    if not has_vector:
        logger.warning("pgvector extension not installed; skipping kb_chunks migration")
        return

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("jira_issue_id", sa.String(length=64), nullable=True),
        sa.Column("jira_key", sa.String(length=64), nullable=True),
        sa.Column("comment_id", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(dim=768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_unique_constraint("uq_kb_chunks_content_hash", "kb_chunks", ["content_hash"])
    op.create_index(op.f("ix_kb_chunks_jira_issue_id"), "kb_chunks", ["jira_issue_id"], unique=False)
    op.create_index(op.f("ix_kb_chunks_jira_key"), "kb_chunks", ["jira_key"], unique=False)
    op.create_index(op.f("ix_kb_chunks_comment_id"), "kb_chunks", ["comment_id"], unique=False)
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw "
        "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_hnsw")
    op.drop_index(op.f("ix_kb_chunks_comment_id"), table_name="kb_chunks")
    op.drop_index(op.f("ix_kb_chunks_jira_key"), table_name="kb_chunks")
    op.drop_index(op.f("ix_kb_chunks_jira_issue_id"), table_name="kb_chunks")
    op.drop_constraint("uq_kb_chunks_content_hash", "kb_chunks", type_="unique")
    op.drop_table("kb_chunks")
