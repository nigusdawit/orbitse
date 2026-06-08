"""billing_links — link a tenant to its PLATFORM Stripe subscription + a plan price label.

Revision ID: 0039_billing_links
Revises: 0038_chatbot_auto_open
Create Date: 2026-06-08

Task 103 (gap §6.2). The Billing view shows the tenant's subscription to THIS platform
(the client paying us), which runs on a separate platform Stripe account
(PLATFORM_STRIPE_SECRET_KEY) from each client's order-checkout Stripe (STRIPE_SECRET_KEY).
To pull live status we store the tenant's platform Stripe customer/subscription ids; to
show a price before Stripe is wired we add an optional plan price label.

Additive + idempotent (ADD COLUMN IF NOT EXISTS) — a fresh boot's init_db creates
tenants/plans without these, then this migration adds them (runs every boot via
_run_alembic_upgrade). All default to '' so nothing changes until an operator links a
tenant / sets a price. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0039_billing_links"
down_revision = "0038_chatbot_auto_open"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS price_display TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS stripe_customer_id")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS stripe_subscription_id")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS price_display")
