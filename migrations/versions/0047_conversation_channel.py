"""conversation channel — make chat_conversations the universal store for chat + SMS + voice.

Revision ID: 0047_conversation_channel
Revises: 0046_web_call_otps
Create Date: 2026-06-09

The Conversations inbox was web-chat only. To show SMS and voice in the same inbox we tag each
conversation with a `channel` ('chat' | 'sms' | 'voice'), a `contact` (the phone number for
sms/voice; blank for chat), and an optional `recording_url` (voice calls). SMS + voice are then
ingested into chat_conversations/chat_messages so the existing list / transcript / polling / human-
takeover machinery works for every channel. Additive + idempotent — existing rows default to 'chat'.
Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0047_conversation_channel"
down_revision = "0046_web_call_otps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS channel VARCHAR(16) NOT NULL DEFAULT 'chat'")
    op.execute("ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS contact VARCHAR(120) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS recording_url VARCHAR(500) NOT NULL DEFAULT ''")
    op.execute("CREATE INDEX IF NOT EXISTS chat_conversations_channel_idx ON chat_conversations (channel, updated_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chat_conversations_channel_idx")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS recording_url")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS contact")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS channel")
