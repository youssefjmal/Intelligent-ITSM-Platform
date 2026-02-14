"""add jira reverse sync fields and state

Revision ID: 0012_jira_reverse_sync
Revises: 0011_add_verification_code
Create Date: 2026-02-14 16:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_jira_reverse_sync"
down_revision = "0011_add_verification_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.add_column("tickets", sa.Column("external_source", sa.String(length=32), nullable=True))
    op.add_column("tickets", sa.Column("external_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(op.f("ix_tickets_external_id"), "tickets", ["external_id"], unique=False)
    op.create_index(op.f("ix_tickets_external_source"), "tickets", ["external_source"], unique=False)
    op.create_unique_constraint(
        "uq_tickets_external_source_external_id",
        "tickets",
        ["external_source", "external_id"],
    )

    op.add_column("ticket_comments", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ticket_comments", sa.Column("external_comment_id", sa.String(length=128), nullable=True))
    op.add_column("ticket_comments", sa.Column("external_source", sa.String(length=32), nullable=True))
    op.add_column("ticket_comments", sa.Column("external_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ticket_comments", sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index(op.f("ix_ticket_comments_external_comment_id"), "ticket_comments", ["external_comment_id"], unique=False)
    op.create_index(op.f("ix_ticket_comments_external_source"), "ticket_comments", ["external_source"], unique=False)
    op.create_unique_constraint(
        "uq_ticket_comments_ticket_external_comment",
        "ticket_comments",
        ["ticket_id", "external_comment_id"],
    )

    op.create_table(
        "jira_sync_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_key", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cursor", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_key"),
    )
    op.create_index(op.f("ix_jira_sync_state_project_key"), "jira_sync_state", ["project_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_jira_sync_state_project_key"), table_name="jira_sync_state")
    op.drop_table("jira_sync_state")

    op.drop_constraint("uq_ticket_comments_ticket_external_comment", "ticket_comments", type_="unique")
    op.drop_index(op.f("ix_ticket_comments_external_source"), table_name="ticket_comments")
    op.drop_index(op.f("ix_ticket_comments_external_comment_id"), table_name="ticket_comments")
    op.drop_column("ticket_comments", "raw_payload")
    op.drop_column("ticket_comments", "external_updated_at")
    op.drop_column("ticket_comments", "external_source")
    op.drop_column("ticket_comments", "external_comment_id")
    op.drop_column("ticket_comments", "updated_at")

    op.drop_constraint("uq_tickets_external_source_external_id", "tickets", type_="unique")
    op.drop_index(op.f("ix_tickets_external_source"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_external_id"), table_name="tickets")
    op.drop_column("tickets", "raw_payload")
    op.drop_column("tickets", "last_synced_at")
    op.drop_column("tickets", "external_updated_at")
    op.drop_column("tickets", "external_source")
    op.drop_column("tickets", "external_id")
