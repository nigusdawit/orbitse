"""campaign_calls — dedup ledger for the Vapi outbound-call automation (slice 4 / automations).

Revision ID: 0043_campaign_calls
Revises: 0042_voice_calls_vapi
Create Date: 2026-06-08

The scheduled vapi_outbound_campaign action calls people matching a status filter. This table
records who a given campaign (automation) has already called so subsequent ticks never re-dial
the same person. UNIQUE(automation_id, audience_table, audience_id) is the idempotency key.
Additive + idempotent. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0043_campaign_calls"
down_revision = "0042_voice_calls_vapi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_calls (
            id             BIGSERIAL PRIMARY KEY,
            tenant_id      INTEGER     NOT NULL DEFAULT 1,
            automation_id  INTEGER     NOT NULL,
            audience_table VARCHAR(40) NOT NULL DEFAULT '',
            audience_id    BIGINT      NOT NULL DEFAULT 0,
            phone          TEXT        NOT NULL DEFAULT '',
            vapi_call_id   VARCHAR(120) NOT NULL DEFAULT '',
            status         VARCHAR(20) NOT NULL DEFAULT 'initiated',
            called_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (automation_id, audience_table, audience_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS campaign_calls_automation_idx ON campaign_calls (automation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_calls")
