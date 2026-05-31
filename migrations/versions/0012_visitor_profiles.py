"""visitor_profiles — per-visitor CRM signals (interests/needs/lead_score/consent).

Revision ID: 0012_visitor_profiles
Revises: 0011_rag_audience
Create Date: 2026-05-31

Phase 6 / Epic D (task 042). Adds a profile row per stable visitor_id so the
concierge can "remember" a visitor's accumulated interests + needs, a 0-100
lead_score, a marketing-consent flag, and a short rolling summary. Populated by
a gated, fail-open background updater after each visitor turn (the 'Visitor CRM'
AI Control knob); when the knob is off the table simply stays empty and behavior
is unchanged. Mirrors the CREATE TABLE in init_db() so a fresh fork is consistent
whether it boots via init_db or the Alembic chain.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0012_visitor_profiles"
down_revision = "0011_rag_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS visitor_profiles (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER NOT NULL DEFAULT 1,
            visitor_id   VARCHAR(100) NOT NULL,
            interests    JSONB NOT NULL DEFAULT '[]'::jsonb,
            needs        JSONB NOT NULL DEFAULT '[]'::jsonb,
            lead_score   INTEGER NOT NULL DEFAULT 0,
            consent      BOOLEAN NOT NULL DEFAULT FALSE,
            summary      TEXT NOT NULL DEFAULT '',
            turns        INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, visitor_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS visitor_profiles_lead_idx "
        "ON visitor_profiles (tenant_id, lead_score DESC, updated_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS visitor_profiles")
