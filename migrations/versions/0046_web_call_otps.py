"""web_call_otps — SMS one-time-codes that verify a visitor owns the number before we dial it.

Revision ID: 0046_web_call_otps
Revises: 0045_web_voice
Create Date: 2026-06-08

The visitor phone-callback is an anonymous auto-dialer; without proof-of-ownership a visitor could
make us ring a third party's phone. This table backs an SMS OTP step: we text a code to the number,
the visitor enters it, and only a verified, unexpired, attempt-limited code unlocks the actual call.
Codes are stored HASHED (never plaintext). Also doubles as the rate-limit ledger for OTP sends
(per phone / per IP). Additive + idempotent. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0046_web_call_otps"
down_revision = "0045_web_voice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS web_call_otps (
            id         BIGSERIAL PRIMARY KEY,
            tenant_id  INTEGER      NOT NULL DEFAULT 1,
            phone      TEXT         NOT NULL DEFAULT '',
            ip         VARCHAR(64)  NOT NULL DEFAULT '',
            code_hash  VARCHAR(128) NOT NULL DEFAULT '',
            attempts   INTEGER      NOT NULL DEFAULT 0,
            verified   BOOLEAN      NOT NULL DEFAULT FALSE,
            expires_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS web_call_otps_phone_idx ON web_call_otps (phone, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS web_call_otps_ip_idx ON web_call_otps (ip, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_call_otps")
