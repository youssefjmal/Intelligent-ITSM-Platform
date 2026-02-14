"""add problem management entities

Revision ID: 0014_problem_mgmt
Revises: 0013_rbac_user_role
Create Date: 2026-02-14 20:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0014_problem_mgmt"
down_revision = "0013_rbac_user_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE problem_status AS ENUM ('open', 'investigating', 'known_error', 'resolved', 'closed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    problem_status = postgresql.ENUM(
        "open",
        "investigating",
        "known_error",
        "resolved",
        "closed",
        name="problem_status",
        create_type=False,
    )

    op.create_table(
        "problems",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                "infrastructure",
                "network",
                "security",
                "application",
                "service_request",
                "hardware",
                "email",
                "problem",
                name="ticket_category",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("status", problem_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrences_count", sa.Integer(), nullable=False),
        sa.Column("active_count", sa.Integer(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("workaround", sa.Text(), nullable=True),
        sa.Column("permanent_fix", sa.Text(), nullable=True),
        sa.Column("similarity_key", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("similarity_key"),
    )
    op.create_index(op.f("ix_problems_similarity_key"), "problems", ["similarity_key"], unique=True)

    op.add_column("tickets", sa.Column("problem_id", sa.String(length=20), nullable=True))
    op.create_index(op.f("ix_tickets_problem_id"), "tickets", ["problem_id"], unique=False)
    op.create_foreign_key(
        "fk_tickets_problem_id_problems",
        "tickets",
        "problems",
        ["problem_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tickets_problem_id_problems", "tickets", type_="foreignkey")
    op.drop_index(op.f("ix_tickets_problem_id"), table_name="tickets")
    op.drop_column("tickets", "problem_id")

    op.drop_index(op.f("ix_problems_similarity_key"), table_name="problems")
    op.drop_table("problems")

    op.execute("DROP TYPE IF EXISTS problem_status")
