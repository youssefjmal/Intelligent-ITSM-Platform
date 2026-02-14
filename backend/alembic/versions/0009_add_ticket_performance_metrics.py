"""add ticket performance metrics

Revision ID: 0009_ticket_perf_metrics
Revises: 0008_add_problem_ticket_category
Create Date: 2026-02-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0009_ticket_perf_metrics"
down_revision = "0008_add_problem_ticket_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ticket_priority_enum = sa.Enum(
        "critical",
        "high",
        "medium",
        "low",
        name="ticket_priority",
        create_type=False,
    )
    ticket_category_enum = sa.Enum(
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
    )

    op.add_column(
        "tickets",
        sa.Column("auto_assignment_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tickets",
        sa.Column("auto_priority_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tickets",
        sa.Column("assignment_model_version", sa.String(length=40), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "tickets",
        sa.Column("priority_model_version", sa.String(length=40), nullable=False, server_default="legacy"),
    )
    op.add_column("tickets", sa.Column("predicted_priority", ticket_priority_enum, nullable=True))
    op.add_column("tickets", sa.Column("predicted_category", ticket_category_enum, nullable=True))
    op.add_column(
        "tickets",
        sa.Column("assignment_change_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("tickets", sa.Column("first_action_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_tickets_auto_assignment_applied",
        "tickets",
        ["auto_assignment_applied"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_auto_assignment_applied", table_name="tickets")
    op.drop_column("tickets", "resolved_at")
    op.drop_column("tickets", "first_action_at")
    op.drop_column("tickets", "assignment_change_count")
    op.drop_column("tickets", "predicted_category")
    op.drop_column("tickets", "predicted_priority")
    op.drop_column("tickets", "priority_model_version")
    op.drop_column("tickets", "assignment_model_version")
    op.drop_column("tickets", "auto_priority_applied")
    op.drop_column("tickets", "auto_assignment_applied")
