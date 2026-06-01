"""add theme_ui_scale to site_settings

Adds an admin-controllable "overall size" (zoom) factor for the public site.
1.0 = 100% (no zoom), values below 1 zoom OUT (smaller components), values
above 1 zoom IN (bigger components). Applied site-wide via CSS `zoom` on the
document root. Defaults to 1.0 so existing installs render identically.

Revision ID: 0020_theme_ui_scale
Revises: 0019_meeting_start_iso
Create Date: 2026-06-01
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0020_theme_ui_scale"
down_revision = "0019_meeting_start_iso"
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS keeps this safe on a DB where the legacy in-code
    # schema path (or a re-run) may have already added the column.
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS theme_ui_scale NUMERIC NOT NULL DEFAULT 1.0"
    )


def downgrade():
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS theme_ui_scale")
