"""wp_onboarding_links — shareable WordPress plugin client onboarding links.

Revision ID: 0007_wp_onboarding_links
Revises: 0006_merge_rag_heads
Create Date: 2026-05-31

The super admin generates one link per client. The client opens
/plugin/onboard/<token> (no login) to download the plugin zip and copy their
pre-filled setup values + step-by-step instructions.

This table is also declared in admin_ai_platform/schema.py's legacy fresh-install
_DDL, but that path only runs end-to-end on a brand-new database — on an existing
DB the live schema is owned by these Alembic migrations, so the table must be
created here too. Mirrors the schema.py DDL exactly (SERIAL-PK convention).
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0007_wp_onboarding_links"
down_revision = "0006_merge_rag_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wp_onboarding_links (
            id              SERIAL PRIMARY KEY,
            token           TEXT UNIQUE NOT NULL,
            tenant_id       INTEGER NOT NULL DEFAULT 1,
            label           TEXT NOT NULL DEFAULT '',
            embed_key       TEXT NOT NULL DEFAULT '',
            include_sso     BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at      TIMESTAMP,
            revoked         BOOLEAN NOT NULL DEFAULT FALSE,
            view_count      INTEGER NOT NULL DEFAULT 0,
            last_viewed_at  TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wp_onboarding_links")
