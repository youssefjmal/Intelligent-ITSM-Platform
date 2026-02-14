"""add verification code to verification tokens

Revision ID: 0011_add_verification_code
Revises: 0010_add_password_reset_tokens
Create Date: 2026-02-14 11:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_add_verification_code"
down_revision = "0010_add_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("verification_tokens", sa.Column("code", sa.String(length=6), nullable=True))
    op.execute(
        "UPDATE verification_tokens "
        "SET code = LPAD((floor(random() * 1000000))::int::text, 6, '0') "
        "WHERE code IS NULL"
    )
    op.alter_column("verification_tokens", "code", existing_type=sa.String(length=6), nullable=False)
    op.create_index(op.f("ix_verification_tokens_code"), "verification_tokens", ["code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_verification_tokens_code"), table_name="verification_tokens")
    op.drop_column("verification_tokens", "code")
