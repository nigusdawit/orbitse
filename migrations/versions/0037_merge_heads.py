"""merge_heads — collapse the two parallel chains that both branch off 0034.

Revision ID: 0037_merge_heads
Revises: 0035_conversation_takeover, 0036_chatbot_theme
Create Date: 2026-06-08

When the Replit team line and the platform line were merged, both had added
migrations off 0034_sentry_alerts:
  * platform: 0034 -> 0035_conversation_takeover            (task 095 inbox)
  * replit:   0034 -> 0035_feature_visibility -> 0036_chatbot_theme
That left Alembic with two heads, so `alembic upgrade head` became ambiguous
(CommandError: Multiple head revisions). This empty merge revision joins them
into a single head again — no DDL, because both upstream chains already created
their own tables/columns. Mirrors the existing 0006_merge_rag_heads pattern.
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


revision = "0037_merge_heads"
down_revision = ("0035_conversation_takeover", "0036_chatbot_theme")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
