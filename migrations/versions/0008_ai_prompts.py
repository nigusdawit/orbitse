"""ai_prompts — super-admin editable AI system prompts (DB-backed, cached).

Revision ID: 0008_ai_prompts
Revises: 0007_wp_onboarding_links
Create Date: 2026-05-31

One row per editable prompt (visitor concierge, admin assistant, slide
narration, SEO generator, persona router, web scraper intros, etc.). The app
pre-fills this table with the current hardcoded defaults at boot via
sync_ai_prompts(), so a super-admin always edits pre-filled text. At runtime
the prompts are served from an in-memory cache (loaded once, refreshed on save)
so there is no per-request DB hit.

This table is also created in app.py's init_db() CREATE TABLE block for
brand-new installs; it is declared here as well because on an existing database
the live schema is owned by these Alembic migrations.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0008_ai_prompts"
down_revision = "0007_wp_onboarding_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_prompts (
            id          SERIAL PRIMARY KEY,
            prompt_key  TEXT UNIQUE NOT NULL,
            content     TEXT NOT NULL DEFAULT '',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by  TEXT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_prompts")
