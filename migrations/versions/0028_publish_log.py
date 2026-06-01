"""publish_log — audit trail for outbound publishes through a capability.

Revision ID: 0028_publish_log
Revises: 0027_content_assets
Create Date: 2026-06-01

Phase 8 (task 067). One row per publish attempt (webhook / http_api / mcp /
python). `detail` stores a truncated, redacted result/error — never secrets.
Mirrors init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0028_publish_log"
down_revision = "0027_content_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_log (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            capability_id BIGINT REFERENCES publish_capabilities(id) ON DELETE SET NULL,
            draft_id      BIGINT REFERENCES content_drafts(id) ON DELETE SET NULL,
            kind          TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT '',
            detail        TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS publish_log_recent_idx "
               "ON publish_log (tenant_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS publish_log")
