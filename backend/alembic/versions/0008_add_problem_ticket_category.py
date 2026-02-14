"""add problem ticket category

Revision ID: 0008_add_problem_ticket_category
Revises: 0007_add_intern_seniority
Create Date: 2026-02-13 00:00:00.000000

"""
from alembic import op

revision = "0008_add_problem_ticket_category"
down_revision = "0007_add_intern_seniority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE ticket_category ADD VALUE IF NOT EXISTS 'problem'")


def downgrade() -> None:
    op.execute("UPDATE tickets SET category = 'service_request' WHERE category = 'problem'")
    op.execute("ALTER TYPE ticket_category RENAME TO ticket_category_old")
    op.execute(
        "CREATE TYPE ticket_category AS ENUM "
        "('infrastructure','network','security','application','service_request','hardware','email')"
    )
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category "
        "USING category::text::ticket_category"
    )
    op.execute("DROP TYPE ticket_category_old")
