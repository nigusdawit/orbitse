"""research & content engine — shared Sources layer + content pipeline tables.

Revision ID: 0026_research_content_engine
Revises: 0025_sql_skill_connection
Create Date: 2026-06-01

Phase 8 (task 062). Foundation for the Research Hub + Content Studio:
  research_reports   — a cited synthesis (Deep Research output).
  research_sources   — raw fetched items (scraper / web / KB / MCP / Datahub),
                       linked to a report; content_hash powers dedup/change.
  content_drafts     — generated content (review-gated) that publishes into the
                       existing content tables (blog_posts, generated pages, …).
  publish_capabilities — super-admin-defined output channels (mcp / webhook /
                       http_api / python), secrets encrypted at rest.
All gated by default-OFF AI Control knobs; mirrors init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0026_research_content_engine"
down_revision = "0025_sql_skill_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research_reports (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER NOT NULL DEFAULT 1,
            topic        TEXT NOT NULL DEFAULT '',
            question     TEXT NOT NULL DEFAULT '',
            summary      TEXT NOT NULL DEFAULT '',
            key_points   JSONB NOT NULL DEFAULT '[]'::jsonb,
            citations    JSONB NOT NULL DEFAULT '[]'::jsonb,
            status       TEXT NOT NULL DEFAULT 'draft',
            model        TEXT NOT NULL DEFAULT '',
            created_by   TEXT NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS research_reports_recent_idx "
               "ON research_reports (tenant_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research_sources (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER NOT NULL DEFAULT 1,
            report_id    BIGINT REFERENCES research_reports(id) ON DELETE CASCADE,
            source_type  TEXT NOT NULL DEFAULT 'web',
            url          TEXT NOT NULL DEFAULT '',
            title        TEXT NOT NULL DEFAULT '',
            content_text TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            fetched_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS research_sources_report_idx "
               "ON research_sources (report_id)")
    op.execute("CREATE INDEX IF NOT EXISTS research_sources_hash_idx "
               "ON research_sources (tenant_id, content_hash)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS content_drafts (
            id              BIGSERIAL PRIMARY KEY,
            tenant_id       INTEGER NOT NULL DEFAULT 1,
            content_type    TEXT NOT NULL DEFAULT 'blog',
            title           TEXT NOT NULL DEFAULT '',
            body            TEXT NOT NULL DEFAULT '',
            meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_report_id BIGINT REFERENCES research_reports(id) ON DELETE SET NULL,
            status          TEXT NOT NULL DEFAULT 'draft',
            target_table    TEXT NOT NULL DEFAULT '',
            target_id       BIGINT,
            created_by      TEXT NOT NULL DEFAULT '',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS content_drafts_recent_idx "
               "ON content_drafts (tenant_id, status, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_capabilities (
            id               BIGSERIAL PRIMARY KEY,
            tenant_id        INTEGER NOT NULL DEFAULT 1,
            name             TEXT NOT NULL DEFAULT '',
            kind             TEXT NOT NULL DEFAULT 'webhook',
            description      TEXT NOT NULL DEFAULT '',
            encrypted_config TEXT NOT NULL DEFAULT '',
            enabled          BOOLEAN NOT NULL DEFAULT FALSE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS publish_capabilities")
    op.execute("DROP TABLE IF EXISTS content_drafts")
    op.execute("DROP TABLE IF EXISTS research_sources")
    op.execute("DROP TABLE IF EXISTS research_reports")
