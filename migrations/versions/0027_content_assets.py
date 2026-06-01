"""content_assets — visual content scaffold (images / diagrams / clips).

Revision ID: 0027_content_assets
Revises: 0026_research_content_engine
Create Date: 2026-06-01

Phase 8 (task 066). A durable record for visual assets generated for a content
draft. A pluggable provider populates url/storage_key/status; the no-spend
default provider just records the plan (status='planned'). Gated by the
visual_content_enabled AI Control knob. Mirrors init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0027_content_assets"
down_revision = "0026_research_content_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS content_assets (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER NOT NULL DEFAULT 1,
            draft_id     BIGINT REFERENCES content_drafts(id) ON DELETE CASCADE,
            report_id    BIGINT REFERENCES research_reports(id) ON DELETE SET NULL,
            asset_type   TEXT NOT NULL DEFAULT 'image',
            provider     TEXT NOT NULL DEFAULT 'placeholder',
            prompt       TEXT NOT NULL DEFAULT '',
            spec         JSONB NOT NULL DEFAULT '{}'::jsonb,
            storage_key  TEXT NOT NULL DEFAULT '',
            url          TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'planned',
            created_by   TEXT NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS content_assets_draft_idx "
               "ON content_assets (draft_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_assets")
