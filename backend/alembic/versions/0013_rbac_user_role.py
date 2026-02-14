"""add user role for rbac

Revision ID: 0013_rbac_user_role
Revises: 0012_jira_reverse_sync
Create Date: 2026-02-14 18:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_rbac_user_role"
down_revision = "0012_jira_reverse_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'user'")
    op.add_column("tickets", sa.Column("reporter_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_tickets_reporter_id"), "tickets", ["reporter_id"], unique=False)


def downgrade() -> None:
    # Enum value removal is intentionally unsupported in downgrade.
    op.drop_index(op.f("ix_tickets_reporter_id"), table_name="tickets")
    op.drop_column("tickets", "reporter_id")
