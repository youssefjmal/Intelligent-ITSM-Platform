"""add network ticket category

Revision ID: 0003_add_network_category
Revises: 0002_recommendations
Create Date: 2026-02-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_network_category"
down_revision = "0002_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE ticket_category ADD VALUE IF NOT EXISTS 'network'")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("UPDATE tickets SET category='infrastructure' WHERE category='network'")
    op.execute("ALTER TYPE ticket_category RENAME TO ticket_category_old")
    op.execute("CREATE TYPE ticket_category AS ENUM ('bug', 'feature', 'support', 'infrastructure', 'security')")
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category "
        "USING category::text::ticket_category"
    )
    op.execute("DROP TYPE ticket_category_old")