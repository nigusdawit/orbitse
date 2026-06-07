"""conversation_takeover — per-conversation human-takeover / AI-pause state.

Revision ID: 0035_conversation_takeover
Revises: 0034_sentry_alerts
Create Date: 2026-06-07

Task 095 (gap §2.4 Conversations inbox, P1). One row per chat_conversations row that a
human has taken over (or had its AI paused). Kept OFF chat_conversations (which is
written on every visitor turn) so the hot path isn't widened; a conversation with NO
row = normal AI mode (the common case). Tenant-scoped for forward-compat though the
store is single-tenant today. NOT in the frozen init_db DDL — Alembic owns post-0030
schema — but the SAME CREATE TABLE is ALSO in the app bootstrap block (alongside
chat_messages) so a fresh boot without Alembic still has it (mirrors chat_*/visitor_
profiles). Idempotent; round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0035_conversation_takeover"
down_revision = "0034_sentry_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_takeover (
            conversation_id INTEGER PRIMARY KEY
                            REFERENCES chat_conversations(id) ON DELETE CASCADE,
            tenant_id       INTEGER NOT NULL DEFAULT 1,
            ai_paused       BOOLEAN NOT NULL DEFAULT FALSE,
            taken_over_by   TEXT    NOT NULL DEFAULT '',
            taken_over_at   TIMESTAMP,
            released_at     TIMESTAMP,
            updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_takeover_active_idx "
        "ON conversation_takeover (tenant_id, ai_paused)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conversation_takeover_active_idx")
    op.execute("DROP TABLE IF EXISTS conversation_takeover")
