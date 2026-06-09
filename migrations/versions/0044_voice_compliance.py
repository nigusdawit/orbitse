"""voice_compliance — recording + consent settings for Vapi calls we initiate.

Revision ID: 0044_voice_compliance
Revises: 0043_campaign_calls
Create Date: 2026-06-08

A single JSONB blob on the singleton site_settings row (id=1), mirroring the appearance
customizer's admin_theme_extra (migration 0033). Holds {recording_enabled, consent_message}.
Applied as Vapi assistantOverrides on every call the platform places (campaign, manual outbound,
in-browser test) so the operator can disable recording or speak a consent disclosure centrally,
without editing each assistant in Vapi. Additive + idempotent. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0044_voice_compliance"
down_revision = "0043_campaign_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE site_settings "
        "ADD COLUMN IF NOT EXISTS voice_compliance JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE site_settings DROP COLUMN IF EXISTS voice_compliance")
