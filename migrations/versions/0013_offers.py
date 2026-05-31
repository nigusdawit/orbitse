"""offers — super-admin-defined promotions the concierge can surface contextually.

Revision ID: 0013_offers
Revises: 0012_visitor_profiles
Create Date: 2026-05-31

Phase 6 / Epic D (task 044). A small offers/deals catalog the visitor concierge
can surface via the gated `lookup_offers` tool. trigger_tags (jsonb array) lets
an offer target visitors with matching interests (empty = always eligible);
active + optional starts_at/ends_at bound when it's live; priority orders them.
Nothing surfaces unless the 'Offers' AI Control knob is on AND the skill is
enabled, so a fresh fork is unaffected. Mirrors the CREATE TABLE in init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0013_offers"
down_revision = "0012_visitor_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS offers (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            title         TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            code          TEXT NOT NULL DEFAULT '',
            cta_url       TEXT NOT NULL DEFAULT '',
            trigger_tags  JSONB NOT NULL DEFAULT '[]'::jsonb,
            active        BOOLEAN NOT NULL DEFAULT TRUE,
            starts_at     TIMESTAMPTZ,
            ends_at       TIMESTAMPTZ,
            priority      INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS offers_active_idx "
        "ON offers (tenant_id, active, priority DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS offers")
