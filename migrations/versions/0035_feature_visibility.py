"""feature_visibility — split per-feature 'function' from 'visibility'.

Revision ID: 0035_feature_visibility
Revises: 0034_sentry_alerts
Create Date: 2026-06-07

Adds a nullable `visible` column to tenant_features so an operator can control
whether a feature's UI (sidebar link + tab) is shown to a client SEPARATELY from
whether the feature's backend function is enabled.

  - enabled  → does the backend function run (enforce_feature_flags gate). UNCHANGED.
  - visible  → does the client see the sidebar link / tab in the admin UI. NEW.

`visible` is nullable with NO server default. NULL means "inherit from enabled",
so every existing tenant behaves EXACTLY as before (shown iff enabled) until an
operator sets visibility explicitly from the Plans & Features tab. This keeps the
change additive and non-breaking — the function gate keeps keying off `enabled`.

NOT added to the frozen in-code init_db() DDL — Alembic owns all post-0030 schema.
Idempotent ADD COLUMN IF NOT EXISTS + a precise downgrade(), so it round-trips.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0035_feature_visibility"
down_revision = "0034_sentry_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, NO default: NULL = "visibility inherits the enabled flag", so every
    # existing row keeps its current behavior (visible iff enabled) until an
    # operator overrides it from the Plans & Features tab.
    op.execute(
        "ALTER TABLE tenant_features ADD COLUMN IF NOT EXISTS visible BOOLEAN"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_features DROP COLUMN IF EXISTS visible")
