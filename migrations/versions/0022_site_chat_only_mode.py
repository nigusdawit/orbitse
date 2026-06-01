"""add chat_only_mode to site_settings

Adds a super-admin-controlled "chat-only mode" flag. When TRUE, the
Replit-hosted public website (landing page + public content pages) stops
serving the full marketing site and shows a minimal placeholder instead,
while the embeddable chat widget, the chat API, and the admin dashboard
keep working. This lets an operator deliver ONLY the embedded AI chat to a
client's own pre-existing website without also exposing a full landing page
at the root URL.

Defaults to FALSE so existing installs are completely unaffected.

Revision ID: 0022_site_chat_only_mode
Revises: 0021_theme_chat_pill_scale
Create Date: 2026-06-01
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0022_site_chat_only_mode"
down_revision = "0021_theme_chat_pill_scale"
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS keeps this safe on a DB where the legacy in-code
    # schema path (or a re-run) may have already added the column.
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS chat_only_mode BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade():
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS chat_only_mode")
