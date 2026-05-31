"""callback_requests.ai_summary — AI handoff summary of the chat for the team.

Revision ID: 0016_callback_summary
Revises: 0015_visitor_personas
Create Date: 2026-05-31

Phase 6 / Epic F (task 048, no-creds part). When the 'handoff_summary_enabled'
knob is on, request_callback generates a short AI summary of the conversation
(what the visitor needs + key context) and stores it here so the team has
context before they call back. Column added for DBs that created
callback_requests under migration 0014; a fresh fork gets it from init_db.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0016_callback_summary"
down_revision = "0015_visitor_personas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE callback_requests "
        "ADD COLUMN IF NOT EXISTS ai_summary TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE callback_requests DROP COLUMN IF EXISTS ai_summary")
