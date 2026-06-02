"""admin appearance ext — expanded super-admin admin-panel theme controls.

Revision ID: 0030_admin_appearance_ext
Revises: 0029_admin_appearance
Create Date: 2026-06-01

Adds the second wave of admin_theme_* columns to site_settings (task 073):
density, UI font scale + family, surface style (glass/solid/minimal), sidebar
style (comfortable/compact/icons), and two accessibility flags (high contrast,
reduce motion). Same migration-managed pattern as 0029; every column has a safe
default so a pre-migration read falls back gracefully. These drive ONLY the
admin panel's own look — the public/visitor theme_* columns are untouched.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0030_admin_appearance_ext"
down_revision = "0029_admin_appearance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_density TEXT NOT NULL DEFAULT 'comfortable'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_font_scale TEXT NOT NULL DEFAULT 'md'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_font_family TEXT NOT NULL DEFAULT 'sans'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_surface TEXT NOT NULL DEFAULT 'glass'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_sidebar TEXT NOT NULL DEFAULT 'comfortable'")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_high_contrast BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS "
               "admin_theme_reduce_motion BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    for col in ("admin_theme_density", "admin_theme_font_scale",
                "admin_theme_font_family", "admin_theme_surface",
                "admin_theme_sidebar", "admin_theme_high_contrast",
                "admin_theme_reduce_motion"):
        op.execute(f"ALTER TABLE site_settings DROP COLUMN IF EXISTS {col}")
