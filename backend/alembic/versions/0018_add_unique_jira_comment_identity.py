"""add unique jira comment identity index on kb_chunks

Revision ID: 0018_add_unique_jira_comment_identity
Revises: 0017_add_ticket_sla_fields
Create Date: 2026-02-18 00:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_add_unique_jira_comment_identity"
down_revision = "0017_add_ticket_sla_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    has_kb_chunks = bool(bind.execute(sa.text("SELECT to_regclass('public.kb_chunks')")).scalar())
    if not has_kb_chunks:
        return

    # Keep the newest row when duplicate comment identities already exist.
    op.execute(
        """
        DELETE FROM kb_chunks t
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY jira_key, comment_id
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS rn
                FROM kb_chunks
                WHERE source_type = 'jira_comment'
                  AND jira_key IS NOT NULL
                  AND comment_id IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE t.id = dupes.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_jira_comment_identity
        ON kb_chunks (jira_key, comment_id)
        WHERE source_type = 'jira_comment'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_jira_comment_identity")
