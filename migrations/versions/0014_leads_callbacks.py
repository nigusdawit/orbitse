"""leads + callback_requests — captured by the agentic-growth tools.

Revision ID: 0014_leads_callbacks
Revises: 0013_offers
Create Date: 2026-05-31

Phase 6 / Epic D (task 045). Backing tables for the gated capture_lead and
request_callback agent tools. The concierge writes a row only when the relevant
AI Control knob is ON, so a fresh fork captures nothing. These hold operator
sales data (the visitor's own contact details, by design). Mirrors the CREATE
TABLE statements in init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0014_leads_callbacks"
down_revision = "0013_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER NOT NULL DEFAULT 1,
            name         TEXT NOT NULL DEFAULT '',
            email        TEXT NOT NULL DEFAULT '',
            phone        TEXT NOT NULL DEFAULT '',
            interest     TEXT NOT NULL DEFAULT '',
            message      TEXT NOT NULL DEFAULT '',
            source       TEXT NOT NULL DEFAULT 'ai_chat',
            visitor_id   VARCHAR(100) NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'new',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS leads_recent_idx ON leads (tenant_id, created_at DESC);")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS callback_requests (
            id             BIGSERIAL PRIMARY KEY,
            tenant_id      INTEGER NOT NULL DEFAULT 1,
            name           TEXT NOT NULL DEFAULT '',
            phone          TEXT NOT NULL DEFAULT '',
            preferred_time TEXT NOT NULL DEFAULT '',
            reason         TEXT NOT NULL DEFAULT '',
            visitor_id     VARCHAR(100) NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS callbacks_recent_idx "
        "ON callback_requests (tenant_id, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS callback_requests")
    op.execute("DROP TABLE IF EXISTS leads")
