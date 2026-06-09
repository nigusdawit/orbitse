"""web_voice — visitor-facing "Talk to us" voice button config + its abuse-control ledger.

Revision ID: 0045_web_voice
Revises: 0044_voice_compliance
Create Date: 2026-06-08

Two additive things:
  * site_settings.web_voice JSONB — super-admin config for the embed widget's voice button
    ({enabled, mode, assistant_id, phone_number_id, button_label, daily_call_cap}). Mirrors the
    voice_compliance blob (migration 0044). Default '{}' → feature OFF.
  * web_call_requests — a ledger of visitor-initiated voice requests, used to RATE-LIMIT the
    anonymous phone-callback path (per IP / per phone / global per day) and to attribute calls.
    The phone callback is an anonymous-triggered auto-dialer, so this table is the spine of its
    abuse controls. Additive + idempotent. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0045_web_voice"
down_revision = "0044_voice_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS web_voice JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS web_call_requests (
            id           BIGSERIAL PRIMARY KEY,
            tenant_id    INTEGER      NOT NULL DEFAULT 1,
            ip           VARCHAR(64)  NOT NULL DEFAULT '',
            phone        TEXT         NOT NULL DEFAULT '',
            mode         VARCHAR(16)  NOT NULL DEFAULT 'phone',
            vapi_call_id VARCHAR(120) NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS web_call_requests_ip_idx ON web_call_requests (ip, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS web_call_requests_phone_idx ON web_call_requests (phone, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_call_requests")
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS web_voice")
