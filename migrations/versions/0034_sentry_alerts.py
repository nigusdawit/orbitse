"""sentry_alerts — inbound Sentry issue-alert webhook intake table.

Revision ID: 0034_sentry_alerts
Revises: 0033_admin_appearance_expand
Create Date: 2026-06-05

Task 092 P2 — give the error-fixing agents a READ path. The SENTRY_DSN is
write-only (the app pushes events TO Sentry but can't read them back), so we
accept Sentry's Issue-Alert webhook at POST /api/sentry/webhook (HMAC-verified,
see admin/observability.py) and upsert one row per Sentry issue here. Agents and
the super-admin Developer-tab "Error Tracking" panel then read from this table /
GET /admin/api/sentry/alerts instead of needing Sentry API credentials.

One row per issue_id (UNIQUE), upserted idempotently so repeated alerts for the
same issue just bump event_count / last_seen / payload rather than duplicating.
Single instance per client (silo deploy) → no tenant fan-out column needed.

NOT added to the frozen in-code init_db() DDL — Alembic owns all post-0030
schema. Idempotent CREATE TABLE IF NOT EXISTS + a precise downgrade(), so the
migration round-trips.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0034_sentry_alerts"
down_revision = "0033_admin_appearance_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per Sentry issue. payload holds the full verified webhook body
    # (JSONB) for agents that want the raw event; the flat columns are the
    # summary the Developer-tab list and the status filter read.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sentry_alerts (
            id            SERIAL PRIMARY KEY,
            issue_id      TEXT NOT NULL UNIQUE,
            title         TEXT NOT NULL DEFAULT '',
            culprit       TEXT NOT NULL DEFAULT '',
            level         TEXT NOT NULL DEFAULT 'error',
            project       TEXT NOT NULL DEFAULT '',
            permalink     TEXT NOT NULL DEFAULT '',
            event_count   INTEGER NOT NULL DEFAULT 1,
            status        TEXT NOT NULL DEFAULT 'new',
            payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
            first_seen    TIMESTAMPTZ,
            last_seen     TIMESTAMPTZ,
            received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Index for the Developer-tab list (newest activity first) and the status
    # filter the agents poll on.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sentry_alerts_status_seen "
        "ON sentry_alerts (status, last_seen DESC NULLS LAST, received_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sentry_alerts_status_seen")
    op.execute("DROP TABLE IF EXISTS sentry_alerts")
