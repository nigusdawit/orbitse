"""meetings — booking requests taken by the concierge's book_meeting tool.

Revision ID: 0017_meetings
Revises: 0016_callback_summary
Create Date: 2026-05-31

Phase 6 / Epic F (task 047). Backing table for the gated book_meeting tool.
status flows 'requested' → 'booked' (set when a connected Calendar MCP confirms
an event; calendar_event_id holds the provider id). With no calendar connected
the row is stored as 'requested' for the team to action. Mirrors the CREATE
TABLE in init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0017_meetings"
down_revision = "0016_callback_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id                BIGSERIAL PRIMARY KEY,
            tenant_id         INTEGER NOT NULL DEFAULT 1,
            name              TEXT NOT NULL DEFAULT '',
            email             TEXT NOT NULL DEFAULT '',
            phone             TEXT NOT NULL DEFAULT '',
            requested_time    TEXT NOT NULL DEFAULT '',
            duration_minutes  INTEGER NOT NULL DEFAULT 30,
            notes             TEXT NOT NULL DEFAULT '',
            status            TEXT NOT NULL DEFAULT 'requested',
            calendar_event_id TEXT NOT NULL DEFAULT '',
            visitor_id        VARCHAR(100) NOT NULL DEFAULT '',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS meetings_recent_idx "
        "ON meetings (tenant_id, created_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meetings")
