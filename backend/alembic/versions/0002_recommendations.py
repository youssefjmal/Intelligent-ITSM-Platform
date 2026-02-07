"""add recommendations table

Revision ID: 0002_recommendations
Revises: 0001_initial
Create Date: 2026-02-07 14:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_recommendations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    rec_type = postgresql.ENUM("pattern", "priority", "solution", "workflow", name="recommendation_type")
    rec_impact = postgresql.ENUM("high", "medium", "low", name="recommendation_impact")

    rec_type_col = postgresql.ENUM("pattern", "priority", "solution", "workflow", name="recommendation_type", create_type=False)
    rec_impact_col = postgresql.ENUM("high", "medium", "low", name="recommendation_impact", create_type=False)

    bind = op.get_bind()
    rec_type.create(bind, checkfirst=True)
    rec_impact.create(bind, checkfirst=True)

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(length=20), primary_key=True, nullable=False),
        sa.Column("type", rec_type_col, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_tickets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("impact", rec_impact_col, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    bind = op.get_bind()
    sa.Enum("high", "medium", "low", name="recommendation_impact").drop(bind, checkfirst=True)
    sa.Enum("pattern", "priority", "solution", "workflow", name="recommendation_type").drop(bind, checkfirst=True)
