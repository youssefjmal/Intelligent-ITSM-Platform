"""Security hardening — user lockout fields + security_events audit table.

Changes
-------
users table:
  - failed_login_attempts  SMALLINT  NOT NULL DEFAULT 0
  - locked_until           TIMESTAMPTZ  NULL

security_events table (new):
  - id             UUID  PK
  - event_type     VARCHAR(64)  NOT NULL  (indexed)
  - user_id        UUID  FK→users.id  ON DELETE SET NULL  NULL  (indexed)
  - actor_id       UUID  FK→users.id  ON DELETE SET NULL  NULL
  - ip_address     VARCHAR(45)  NULL
  - user_agent     VARCHAR(512) NULL
  - metadata       JSONB  NOT NULL  DEFAULT '{}'
  - note           TEXT  NULL
  - created_at     TIMESTAMPTZ  NOT NULL  DEFAULT now()  (indexed)

Revision ID: 0035_security_hardening
Revises: 0034_add_ai_classification_logs
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0035_security_hardening"
down_revision = "0034_add_ai_classification_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users table: lockout columns ─────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )

    # ── security_events table ────────────────────────────────────────────────
    op.create_table(
        "security_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("event_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    op.drop_index("ix_security_events_event_type", table_name="security_events")
    op.drop_table("security_events")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
