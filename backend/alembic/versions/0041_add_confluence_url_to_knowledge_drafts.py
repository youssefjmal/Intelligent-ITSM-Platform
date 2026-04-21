"""add confluence_url to knowledge_drafts

Adds the confluence_url column that stores the full browser URL of the
Confluence page created when a knowledge draft is published to the JSM KB.
Null until the draft has been published via the Confluence integration.

Revision ID: 0041_add_confluence_url_to_knowledge_drafts
Revises: 0040_add_knowledge_drafts
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_add_confluence_url_to_knowledge_drafts"
down_revision = "0040_add_knowledge_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_drafts",
        sa.Column("confluence_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_drafts", "confluence_url")
