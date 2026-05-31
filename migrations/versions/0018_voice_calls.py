"""voice_calls — inbound Twilio Voice calls routed to the AI concierge.

Revision ID: 0018_voice_calls
Revises: 0017_meetings
Create Date: 2026-05-31

Phase 6 / Epic F (task 049). One row per inbound Twilio Voice call. The live
media bridge (Twilio <Stream> ↔ a realtime voice model) is the credential/infra
leg deferred to an operator runbook; this table + the voice webhooks log and
track calls so the feature is observable. Nothing happens unless the
'live_call_enabled' knob is on. Mirrors the CREATE TABLE in init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0018_voice_calls"
down_revision = "0017_meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_calls (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            call_sid      VARCHAR(64) NOT NULL DEFAULT '',
            from_number   TEXT NOT NULL DEFAULT '',
            to_number     TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'initiated',
            summary       TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS voice_calls_recent_idx "
        "ON voice_calls (tenant_id, created_at DESC);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS voice_calls_sid_idx ON voice_calls (call_sid);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS voice_calls")
