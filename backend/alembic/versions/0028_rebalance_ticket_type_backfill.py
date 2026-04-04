"""Rebalance ticket type backfill using text heuristics.

Revision ID: 0028_ticket_type_rebal
Revises: 0027_add_ticket_type
Create Date: 2026-03-13 23:55:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0028_ticket_type_rebal"
down_revision = "0027_add_ticket_type"
branch_labels = None
depends_on = None


SERVICE_REQUEST_PATTERNS = (
    "%request%",
    "%demande%",
    "%need access%",
    "%access request%",
    "%permission%",
    "%permissions%",
    "%install%",
    "%installation%",
    "%new account%",
    "%create account%",
    "%request new%",
    "%onboard%",
    "%onboarding%",
    "%setup%",
    "%configure%",
    "%enable%",
)


def _service_request_clause(column_sql: str) -> str:
    return " OR ".join(f"{column_sql} LIKE '{pattern}'" for pattern in SERVICE_REQUEST_PATTERNS)


def upgrade() -> None:
    text_expr = "LOWER(COALESCE(title, '') || ' ' || COALESCE(description, ''))"
    op.execute(
        f"""
        UPDATE tickets
        SET ticket_type = 'service_request'::ticket_type
        WHERE {_service_request_clause(text_expr)}
        """
    )


def downgrade() -> None:
    text_expr = "LOWER(COALESCE(title, '') || ' ' || COALESCE(description, ''))"
    op.execute(
        f"""
        UPDATE tickets
        SET ticket_type = 'incident'::ticket_type
        WHERE {_service_request_clause(text_expr)}
        """
    )
