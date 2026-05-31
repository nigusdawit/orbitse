"""meetings.start_iso — normalized RFC 3339 start time for calendar pushes.

Revision ID: 0019_meeting_start_iso
Revises: 0018_voice_calls
Create Date: 2026-05-31

Phase 6 / Epic F activation (task 051). book_meeting now normalizes the
visitor's stated time to a real ISO 8601 / RFC 3339 timestamp (the model
supplies it, validated server-side) so a connected Calendar MCP receives a
valid `start` instead of free text. requested_time keeps the human phrasing for
display. Column added for DBs created under migration 0017; a fresh fork gets
it from init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0019_meeting_start_iso"
down_revision = "0018_voice_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS start_iso TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE meetings DROP COLUMN IF EXISTS start_iso")
