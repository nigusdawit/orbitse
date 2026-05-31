"""activity_surface — tag each AI activity row with its surface (admin|visitor).

Revision ID: 0010_activity_surface
Revises: 0009_ai_control_activity
Create Date: 2026-05-31

Phase 6 / Epic A. The Admin AI already logs each turn to ai_activity_log
(migration 0009). We now also log VISITOR turns there, so we add a `surface`
column to tell them apart (default 'admin' for existing rows). Also added to
app.py's init_db CREATE block for fresh installs.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0010_activity_surface"
down_revision = "0009_ai_control_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_activity_log "
        "ADD COLUMN IF NOT EXISTS surface TEXT NOT NULL DEFAULT 'admin'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ai_activity_log_surface_idx "
        "ON ai_activity_log (surface, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ai_activity_log_surface_idx")
    op.execute("ALTER TABLE ai_activity_log DROP COLUMN IF EXISTS surface")
