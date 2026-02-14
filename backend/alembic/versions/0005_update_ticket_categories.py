"""update ticket categories

Revision ID: 0005_update_ticket_categories
Revises: 0004_user_auto_assign_fields
Create Date: 2026-02-09 00:00:00.000000

"""
from alembic import op

revision = "0005_update_ticket_categories"
down_revision = "0004_user_auto_assign_fields"
branch_labels = None
depends_on = None


NEW_VALUES = (
    "infrastructure",
    "network",
    "security",
    "application",
    "service_request",
    "hardware",
    "email",
)

OLD_VALUES = (
    "bug",
    "feature",
    "support",
    "infrastructure",
    "network",
    "security",
)


def upgrade() -> None:
    op.execute("DROP TYPE IF EXISTS ticket_category_new")
    op.execute(
        "CREATE TYPE ticket_category_new AS ENUM "
        "('infrastructure','network','security','application','service_request','hardware','email')"
    )
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category_new "
        "USING (CASE "
        "WHEN category::text IN ('bug','feature') THEN 'application' "
        "WHEN category::text = 'support' THEN 'service_request' "
        "ELSE category::text "
        "END)::ticket_category_new"
    )
    op.execute("DROP TYPE ticket_category")
    op.execute("ALTER TYPE ticket_category_new RENAME TO ticket_category")


def downgrade() -> None:
    op.execute("DROP TYPE IF EXISTS ticket_category_old")
    op.execute(
        "CREATE TYPE ticket_category_old AS ENUM "
        "('bug','feature','support','infrastructure','network','security')"
    )
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category_old "
        "USING (CASE "
        "WHEN category::text = 'application' THEN 'bug' "
        "WHEN category::text IN ('service_request','hardware','email') THEN 'support' "
        "ELSE category::text "
        "END)::ticket_category_old"
    )
    op.execute("DROP TYPE ticket_category")
    op.execute("ALTER TYPE ticket_category_old RENAME TO ticket_category")
