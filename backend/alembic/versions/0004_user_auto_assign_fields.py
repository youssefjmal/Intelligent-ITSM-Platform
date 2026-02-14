"""add auto-assignment fields to users

Revision ID: 0004_user_auto_assign_fields
Revises: 0003_add_network_category
Create Date: 2026-02-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_user_auto_assign_fields"
down_revision = "0003_add_network_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seniority_enum = postgresql.ENUM("junior", "middle", "senior", name="user_seniority")
    seniority_col = postgresql.ENUM(
        "junior",
        "middle",
        "senior",
        name="user_seniority",
        create_type=False,
    )

    bind = op.get_bind()
    seniority_enum.create(bind, checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "specializations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "seniority_level",
            seniority_col,
            nullable=False,
            server_default="middle",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "max_concurrent_tickets",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "max_concurrent_tickets")
    op.drop_column("users", "is_available")
    op.drop_column("users", "seniority_level")
    op.drop_column("users", "specializations")
    bind = op.get_bind()
    sa.Enum("junior", "middle", "senior", name="user_seniority").drop(bind, checkfirst=True)