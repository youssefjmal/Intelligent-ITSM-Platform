"""add intern seniority level

Revision ID: 0007_add_intern_seniority
Revises: 0006_add_refresh_tokens
Create Date: 2026-02-13 00:00:00.000000

"""
from alembic import op

revision = "0007_add_intern_seniority"
down_revision = "0006_add_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_seniority ADD VALUE IF NOT EXISTS 'intern'")


def downgrade() -> None:
    op.execute("UPDATE users SET seniority_level = 'junior' WHERE seniority_level = 'intern'")
    op.execute("ALTER TYPE user_seniority RENAME TO user_seniority_old")
    op.execute("CREATE TYPE user_seniority AS ENUM ('junior', 'middle', 'senior')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN seniority_level TYPE user_seniority "
        "USING seniority_level::text::user_seniority"
    )
    op.execute("DROP TYPE user_seniority_old")
