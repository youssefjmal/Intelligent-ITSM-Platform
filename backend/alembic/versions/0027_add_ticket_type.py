"""add ticket type fields

Revision ID: 0027_add_ticket_type
Revises: 0026_add_ai_solution_feedback
Create Date: 2026-03-13 23:59:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_add_ticket_type"
down_revision = "0026_add_ai_solution_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ticket_type_enum = sa.Enum("incident", "service_request", name="ticket_type")
    ticket_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tickets",
        sa.Column("ticket_type", ticket_type_enum, nullable=False, server_default="service_request"),
    )
    op.add_column(
        "tickets",
        sa.Column("predicted_ticket_type", ticket_type_enum, nullable=True),
    )

    op.execute(
        """
        UPDATE tickets
        SET ticket_type = (
            CASE
                WHEN category::text = 'service_request' THEN 'service_request'
                ELSE 'incident'
            END
        )::ticket_type
        """
    )
    op.execute(
        """
        UPDATE tickets
        SET predicted_ticket_type = (
            CASE
                WHEN predicted_category IS NULL THEN NULL
                WHEN predicted_category::text = 'service_request' THEN 'service_request'
                ELSE 'incident'
            END
        )::ticket_type
        """
    )

    op.alter_column("tickets", "ticket_type", server_default=None)


def downgrade() -> None:
    op.drop_column("tickets", "predicted_ticket_type")
    op.drop_column("tickets", "ticket_type")
    sa.Enum(name="ticket_type").drop(op.get_bind(), checkfirst=True)
