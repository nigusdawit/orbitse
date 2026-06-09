"""voice_calls_vapi — Vapi call fields on voice_calls (Vapi integration, slice 1).

Revision ID: 0042_voice_calls_vapi
Revises: 0041_admin_users_rbac
Create Date: 2026-06-08

Vapi is added as a second voice provider alongside Twilio. Rather than a new table, we
extend voice_calls so Vapi calls show up in the same Voice surface / admin list. Additive +
idempotent; existing Twilio rows default provider='twilio'. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0042_voice_calls_vapi"
down_revision = "0041_admin_users_rbac"
branch_labels = None
depends_on = None


_COLS = [
    ("provider", "VARCHAR(20) NOT NULL DEFAULT 'twilio'"),
    ("vapi_call_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("assistant_id", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("direction", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("duration_seconds", "NUMERIC(10,2) NOT NULL DEFAULT 0"),
    ("cost_usd", "NUMERIC(14,8) NOT NULL DEFAULT 0"),
    ("ended_reason", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("transcript", "TEXT NOT NULL DEFAULT ''"),
    ("recording_url", "TEXT NOT NULL DEFAULT ''"),
]


def upgrade() -> None:
    for name, decl in _COLS:
        op.execute(f"ALTER TABLE voice_calls ADD COLUMN IF NOT EXISTS {name} {decl}")
    op.execute("CREATE INDEX IF NOT EXISTS voice_calls_vapi_idx ON voice_calls (vapi_call_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS voice_calls_vapi_idx")
    for name, _ in _COLS:
        op.execute(f"ALTER TABLE voice_calls DROP COLUMN IF EXISTS {name}")
