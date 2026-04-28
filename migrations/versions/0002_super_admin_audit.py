"""super_admin_audit — append-only log of super-admin lock events.

Revision ID: 0002_super_admin_audit
Revises: 0001_baseline
Create Date: 2026-04-28

Records every unlock attempt (success / invalid_key / throttled), every
manual lock, every auto-lock when the sliding TTL expires, and the
implicit lock that happens on logout. One row per event so an operator
can see who used the super-admin key and when.

Schema mirrors the SERIAL-PK convention used by the legacy init_db()
tables (see app.py — most _log / _audit tables there use SERIAL).
Append-only by convention; no UPDATE or DELETE in app code.
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_super_admin_audit"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS super_admin_audit (
            id          SERIAL PRIMARY KEY,
            ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ip          TEXT,
            user_agent  TEXT,
            action      TEXT NOT NULL,
            outcome     TEXT NOT NULL,
            reason      TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_super_admin_audit_ts "
        "ON super_admin_audit (ts DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_super_admin_audit_ts")
    op.execute("DROP TABLE IF EXISTS super_admin_audit")
