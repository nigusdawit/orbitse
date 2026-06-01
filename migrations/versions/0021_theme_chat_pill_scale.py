"""add theme_chat_pill_scale to site_settings

Adds an admin-controllable size factor for the public chat "pill" (the
collapsed chatbot bar / floating launcher button). 1.0 = 100% (default),
values below 1 make the pill smaller, values above 1 make it bigger.
Applied via CSS `zoom` scoped to the chat pill only — it does NOT affect
the expanded chat panel. Defaults to 1.0 so existing installs render
identically.

Revision ID: 0021_theme_chat_pill_scale
Revises: 0020_theme_ui_scale
Create Date: 2026-06-01
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0021_theme_chat_pill_scale"
down_revision = "0020_theme_ui_scale"
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS keeps this safe on a DB where the legacy in-code
    # schema path (or a re-run) may have already added the column.
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS theme_chat_pill_scale NUMERIC NOT NULL DEFAULT 1.0"
    )


def downgrade():
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS theme_chat_pill_scale")
