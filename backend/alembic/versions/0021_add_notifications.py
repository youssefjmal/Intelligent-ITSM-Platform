"""add notifications table

Revision ID: 0021_add_notifications
Revises: 0020_add_jira_native_waiting_statuses
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_add_notifications"
down_revision = "0020_add_jira_native_waiting_statuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("link", sa.String(length=512), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index("ix_notifications_user_id_read_at", "notifications", ["user_id", "read_at"], unique=False)
    op.execute("ALTER TABLE notifications ALTER COLUMN severity DROP DEFAULT")


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")

