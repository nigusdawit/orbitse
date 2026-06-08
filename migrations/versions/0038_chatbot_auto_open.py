"""chatbot_auto_open — proactive greeting auto-open delay on chatbot_settings.

Revision ID: 0038_chatbot_auto_open
Revises: 0037_merge_heads
Create Date: 2026-06-08

Task 101 (gap §3.2). Adds chatbot_settings.auto_open_seconds (0 = off, the default) so
the visitor concierge widget can auto-open after N seconds. Additive + idempotent
(ADD COLUMN IF NOT EXISTS); a fresh boot's init_db creates chatbot_settings without it,
then this migration adds it (runs on every boot via _run_alembic_upgrade). Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0038_chatbot_auto_open"
down_revision = "0037_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS auto_open_seconds INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chatbot_settings DROP COLUMN IF EXISTS auto_open_seconds")
