"""admin appearance — super-admin-controllable glassmorphic theme for the admin panel.

Revision ID: 0029_admin_appearance
Revises: 0028_publish_log
Create Date: 2026-06-01

Adds admin_theme_* columns to site_settings (migration-managed, like the
theme_ui_scale / theme_chat_pill_scale columns from 0020-0022). These drive the
admin panel's OWN glassmorphic look (distinct from the public-site theme_*
columns): mode (light/dark), accent + secondary accent, blur px, corner radius,
glass surface opacity, and background-glow strength. All have safe defaults so a
pre-migration read falls back gracefully.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0029_admin_appearance"
down_revision = "0028_publish_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_mode TEXT NOT NULL DEFAULT 'dark'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_accent TEXT NOT NULL DEFAULT '#6c8cff'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_accent2 TEXT NOT NULL DEFAULT '#9a7cff'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_blur NUMERIC NOT NULL DEFAULT 18")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_radius NUMERIC NOT NULL DEFAULT 16")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_glass NUMERIC NOT NULL DEFAULT 0.55")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_glow NUMERIC NOT NULL DEFAULT 0.5")


def downgrade() -> None:
    for col in ("admin_theme_mode", "admin_theme_accent", "admin_theme_accent2",
                "admin_theme_blur", "admin_theme_radius", "admin_theme_glass",
                "admin_theme_glow"):
        op.execute(f"ALTER TABLE site_settings DROP COLUMN IF EXISTS {col}")
