"""ai_control_activity — super-admin AI Control settings + AI Activity log.

Revision ID: 0009_ai_control_activity
Revises: 0008_ai_prompts
Create Date: 2026-05-31

Phase 5. Two tables:

* ai_control_settings — one row per tunable Admin-AI knob (timeout, retries,
  provider fallback, rate limit, history budget/summarize, response cache,
  sqlguard, redact, activity logging). Absent row = fall back to the env var,
  then the registry default. Edited from the super-admin "AI Control" tab.

* ai_activity_log — one row per admin-AI turn (model, rounds, tools, tokens,
  cost, duration, status, plus the redacted question + final answer). Powers the
  super-admin "AI Activity" tab.

Both are ALSO created in app.py's init_db() CREATE TABLE block for brand-new
installs (so a freshly forked client works with no manual migration); they are
declared here as well because on an existing database the live schema is owned
by these Alembic migrations.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0009_ai_control_activity"
down_revision = "0008_ai_prompts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_control_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL DEFAULT '',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by  TEXT NOT NULL DEFAULT ''
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_activity_log (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            session_id    TEXT,
            model         TEXT,
            provider      TEXT,
            rounds        INTEGER NOT NULL DEFAULT 0,
            tool_calls    INTEGER NOT NULL DEFAULT 0,
            tokens_in     INTEGER NOT NULL DEFAULT 0,
            tokens_out    INTEGER NOT NULL DEFAULT 0,
            cost_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
            duration_ms   INTEGER NOT NULL DEFAULT 0,
            status        TEXT,
            error_text    TEXT,
            user_message  TEXT,
            final_answer  TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ai_activity_log_recent_idx "
        "ON ai_activity_log (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_activity_log")
    op.execute("DROP TABLE IF EXISTS ai_control_settings")
