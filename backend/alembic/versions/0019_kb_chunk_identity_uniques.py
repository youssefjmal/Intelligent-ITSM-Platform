"""align kb_chunks uniqueness with jira identities

Revision ID: 0019_kb_chunk_identity_uniques
Revises: 0018_add_unique_jira_comment_identity
Create Date: 2026-02-18 13:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_kb_chunk_identity_uniques"
down_revision = "0018_add_unique_jira_comment_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    has_kb_chunks = bool(bind.execute(sa.text("SELECT to_regclass('public.kb_chunks')")).scalar())
    if not has_kb_chunks:
        return

    # Keep the newest chunk per Jira comment identity.
    op.execute(
        """
        DELETE FROM kb_chunks t
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY source_type, jira_key, comment_id
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

    # Keep the newest chunk per Jira issue identity.
    op.execute(
        """
        DELETE FROM kb_chunks t
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY source_type, jira_issue_id
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS rn
                FROM kb_chunks
                WHERE source_type = 'jira_issue'
                  AND jira_issue_id IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE t.id = dupes.id
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_kb_chunks_content_hash'
            ) THEN
                ALTER TABLE kb_chunks DROP CONSTRAINT uq_kb_chunks_content_hash;
            END IF;
        END$$;
        """
    )

    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_jira_comment_identity")
    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_jira_issue_identity")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_chunks_content_hash ON kb_chunks (content_hash)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_jira_comment_identity
        ON kb_chunks (source_type, jira_key, comment_id)
        WHERE source_type = 'jira_comment'
          AND jira_key IS NOT NULL
          AND comment_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_jira_issue_identity
        ON kb_chunks (source_type, jira_issue_id)
        WHERE source_type = 'jira_issue'
          AND jira_issue_id IS NOT NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_kb_chunks = bool(bind.execute(sa.text("SELECT to_regclass('public.kb_chunks')")).scalar())
    if not has_kb_chunks:
        return

    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_jira_issue_identity")
    op.execute("DROP INDEX IF EXISTS uq_kb_chunks_jira_comment_identity")
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_content_hash")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_chunks_jira_comment_identity
        ON kb_chunks (jira_key, comment_id)
        WHERE source_type = 'jira_comment'
        """
    )

    op.execute(
        """
        DELETE FROM kb_chunks t
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY content_hash
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS rn
                FROM kb_chunks
                WHERE content_hash IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE t.id = dupes.id
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_kb_chunks_content_hash'
            ) THEN
                ALTER TABLE kb_chunks
                ADD CONSTRAINT uq_kb_chunks_content_hash UNIQUE (content_hash);
            END IF;
        END$$;
        """
    )
