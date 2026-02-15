"""add jira native sync fields and constraints

Revision ID: 0015_jira_native_sync_fields
Revises: 0014_problem_mgmt
Create Date: 2026-02-15 18:10:00.000000
"""

import sqlalchemy as sa
from alembic import op


revision = "0015_jira_native_sync_fields"
down_revision = "0014_problem_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("source", sa.String(length=32), server_default="local", nullable=False))
    op.add_column("tickets", sa.Column("jira_key", sa.String(length=64), nullable=True))
    op.add_column("tickets", sa.Column("jira_issue_id", sa.String(length=64), nullable=True))
    op.add_column("tickets", sa.Column("jira_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("jira_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_tickets_source"), "tickets", ["source"], unique=False)
    op.create_index(op.f("ix_tickets_jira_key"), "tickets", ["jira_key"], unique=False)
    op.create_index(op.f("ix_tickets_jira_issue_id"), "tickets", ["jira_issue_id"], unique=False)

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                external_id,
                ROW_NUMBER() OVER (PARTITION BY external_id ORDER BY created_at ASC, id ASC) AS rn
            FROM tickets
            WHERE external_id IS NOT NULL
        )
        UPDATE tickets AS t
        SET
            jira_key = COALESCE(t.jira_key, CASE WHEN ranked.rn = 1 THEN ranked.external_id ELSE NULL END),
            jira_issue_id = COALESCE(t.jira_issue_id, CASE WHEN ranked.rn = 1 THEN ranked.external_id ELSE NULL END),
            jira_created_at = COALESCE(t.jira_created_at, t.created_at),
            jira_updated_at = COALESCE(t.jira_updated_at, t.external_updated_at, t.updated_at),
            source = CASE
                WHEN COALESCE(t.external_source, '') IN ('jira', 'jsm') OR t.external_id IS NOT NULL THEN 'jira'
                ELSE 'local'
            END
        FROM ranked
        WHERE ranked.id = t.id
        """
    )
    op.execute("UPDATE tickets SET source='local' WHERE source IS NULL OR source = ''")

    op.create_unique_constraint("uq_tickets_jira_key", "tickets", ["jira_key"])
    op.create_unique_constraint("uq_tickets_jira_issue_id", "tickets", ["jira_issue_id"])
    op.alter_column("tickets", "source", server_default=None)

    op.add_column("ticket_comments", sa.Column("jira_comment_id", sa.String(length=64), nullable=True))
    op.add_column("ticket_comments", sa.Column("jira_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ticket_comments", sa.Column("jira_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_ticket_comments_jira_comment_id"), "ticket_comments", ["jira_comment_id"], unique=False)

    op.execute(
        """
        WITH ranked_comments AS (
            SELECT
                id,
                external_comment_id,
                ROW_NUMBER() OVER (PARTITION BY external_comment_id ORDER BY created_at ASC, id ASC) AS rn
            FROM ticket_comments
            WHERE external_comment_id IS NOT NULL
        )
        UPDATE ticket_comments AS tc
        SET
            jira_comment_id = COALESCE(tc.jira_comment_id, CASE WHEN ranked_comments.rn = 1 THEN ranked_comments.external_comment_id ELSE NULL END),
            jira_created_at = COALESCE(tc.jira_created_at, tc.created_at),
            jira_updated_at = COALESCE(tc.jira_updated_at, tc.external_updated_at, tc.updated_at)
        FROM ranked_comments
        WHERE ranked_comments.id = tc.id
        """
    )
    op.create_unique_constraint("uq_ticket_comments_jira_comment_id", "ticket_comments", ["jira_comment_id"])

    op.add_column("jira_sync_state", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jira_sync_state", "last_error")

    op.drop_constraint("uq_ticket_comments_jira_comment_id", "ticket_comments", type_="unique")
    op.drop_index(op.f("ix_ticket_comments_jira_comment_id"), table_name="ticket_comments")
    op.drop_column("ticket_comments", "jira_updated_at")
    op.drop_column("ticket_comments", "jira_created_at")
    op.drop_column("ticket_comments", "jira_comment_id")

    op.drop_constraint("uq_tickets_jira_issue_id", "tickets", type_="unique")
    op.drop_constraint("uq_tickets_jira_key", "tickets", type_="unique")
    op.drop_index(op.f("ix_tickets_jira_issue_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_jira_key"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_source"), table_name="tickets")
    op.drop_column("tickets", "jira_updated_at")
    op.drop_column("tickets", "jira_created_at")
    op.drop_column("tickets", "jira_issue_id")
    op.drop_column("tickets", "jira_key")
    op.drop_column("tickets", "source")
