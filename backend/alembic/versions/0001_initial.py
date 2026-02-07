"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-02-06 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_role = postgresql.ENUM("admin", "agent", "viewer", name="user_role")
    ticket_status = postgresql.ENUM("open", "in-progress", "pending", "resolved", "closed", name="ticket_status")
    ticket_priority = postgresql.ENUM("critical", "high", "medium", "low", name="ticket_priority")
    ticket_category = postgresql.ENUM("bug", "feature", "support", "infrastructure", "security", name="ticket_category")
    email_kind = postgresql.ENUM("verification", "welcome", name="email_kind")

    user_role_col = postgresql.ENUM("admin", "agent", "viewer", name="user_role", create_type=False)
    ticket_status_col = postgresql.ENUM("open", "in-progress", "pending", "resolved", "closed", name="ticket_status", create_type=False)
    ticket_priority_col = postgresql.ENUM("critical", "high", "medium", "low", name="ticket_priority", create_type=False)
    ticket_category_col = postgresql.ENUM("bug", "feature", "support", "infrastructure", "security", name="ticket_category", create_type=False)
    email_kind_col = postgresql.ENUM("verification", "welcome", name="email_kind", create_type=False)

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    ticket_status.create(bind, checkfirst=True)
    ticket_priority.create(bind, checkfirst=True)
    ticket_category.create(bind, checkfirst=True)
    email_kind.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_col, nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("google_id", sa.String(length=255), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(length=20), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", ticket_status_col, nullable=False),
        sa.Column("priority", ticket_priority_col, nullable=False),
        sa.Column("category", ticket_category_col, nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=False),
        sa.Column("reporter", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.String(length=20), primary_key=True, nullable=False),
        sa.Column("ticket_id", sa.String(length=20), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "email_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("to", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", email_kind_col, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "verification_tokens",
        sa.Column("token", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("verification_tokens")
    op.drop_table("email_logs")
    op.drop_table("ticket_comments")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    sa.Enum("verification", "welcome", name="email_kind").drop(bind, checkfirst=True)
    sa.Enum("bug", "feature", "support", "infrastructure", "security", name="ticket_category").drop(bind, checkfirst=True)
    sa.Enum("critical", "high", "medium", "low", name="ticket_priority").drop(bind, checkfirst=True)
    sa.Enum("open", "in-progress", "pending", "resolved", "closed", name="ticket_status").drop(bind, checkfirst=True)
    sa.Enum("admin", "agent", "viewer", name="user_role").drop(bind, checkfirst=True)
