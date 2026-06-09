"""team_members.extra — per-member custom fields for section templates (Option B).

Revision ID: 0048_team_extra
Revises: 0047_conversation_channel
Create Date: 2026-06-09

A flexible JSONB bag on each team member so section template variants can carry extra per-row data
(e.g. video_url, tagline, accent) that a variant declares via its `item_fields` schema and the admin
edits — without a migration per new field. Additive + idempotent; defaults to '{}'. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0048_team_extra"
down_revision = "0047_conversation_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE team_members ADD COLUMN IF NOT EXISTS extra JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE team_members DROP COLUMN IF EXISTS extra")
