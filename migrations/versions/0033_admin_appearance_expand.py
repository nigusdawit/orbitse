"""admin_appearance_expand — a lot more super-admin Appearance controls in ONE JSONB blob.

Revision ID: 0033_admin_appearance_expand
Revises: 0032_admin_ai_config
Create Date: 2026-06-04

Task 089 — greatly expand the admin-panel Appearance customizer (semantic/utility
colors, typography, shape & depth, layout & motion, per-theme base colors, and
save-your-own presets) WITHOUT a column-per-knob explosion.

Design: the 14 existing discrete columns (admin_theme_* from migrations
0029/0030) stay UNTOUCHED — zero regression risk. Everything new lives in a
single `site_settings.admin_theme_extra` JSONB blob:

  * theme-agnostic knobs (color_success, head_font, shadow, line_height, …) are
    stored ONLY when they differ from the code default, so a future default
    change still reaches any knob the super-admin never touched.
  * per-theme base colors are stored as bg_dark / bg_light / surface_dark / …
    and ALSO only when customized, so the built-in light/dark palette keeps
    flowing from theme.css for every un-customized color.
  * custom_presets — a small (≤24) array of {id,label,settings} snapshots.

Adding a new control after this is a Python-registry entry + a UI control, never
another migration (app-not-script configurability). The blob is fully validated
on read AND write (see _ADMIN_APPEARANCE_EXTRA / _coerce_appearance_extra in
app.py), so a corrupt value can never break the CSS or the editor.

NOT added to the frozen in-code init_db() DDL — Alembic owns all post-0030
schema. Idempotent ADD COLUMN IF NOT EXISTS + a precise downgrade(), so the
migration round-trips.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0033_admin_appearance_expand"
down_revision = "0032_admin_ai_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One nullable-default JSONB column holds every expanded knob. DEFAULT '{}'
    # means a pre-migration / never-saved row reads as "all code defaults" via
    # the fail-open reader, so the admin renders byte-identical to today.
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS admin_theme_extra JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS admin_theme_extra")
