"""chatbot_theme — add a JSONB `theme` column to chatbot_settings.

Revision ID: 0036_chatbot_theme
Revises: 0035_feature_visibility
Create Date: 2026-06-08

Adds a single JSONB `theme` column to the chatbot_settings singleton so the admin
Chatbot tab can store the visual look of the public chat widget WITHOUT a code
change per setting. The object holds (all optional, with public-side fallbacks):

  - shape      : "pill" | "rounded" | "square"  (pill border-radius of the bar)
  - glass      : bool                            (glassmorphic blur on/off)
  - glass_mode : "dark" | "light"               (frost base — for text contrast)
  - tint       : "#rrggbb"                       (surface tint color, optional)
  - text_color : "#rrggbb"                       (chat text color, optional)

One JSONB column (not five scalar columns) keeps the schema small and lets us add
more look-and-feel knobs later with no further migration. Default '{}' means
"use the built-in look", so every existing install is unchanged until an operator
sets a theme.

NOT added to the frozen in-code init_db() DDL — Alembic owns all post-0030 schema.
Idempotent ADD COLUMN IF NOT EXISTS + a precise downgrade(), so it round-trips.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0036_chatbot_theme"
down_revision = "0035_feature_visibility"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS theme JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade():
    op.execute("ALTER TABLE chatbot_settings DROP COLUMN IF EXISTS theme")
