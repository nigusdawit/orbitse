"""plan_stripe_price — map a plan to a platform Stripe product/price.

Revision ID: 0040_plan_stripe_price
Revises: 0039_billing_links
Create Date: 2026-06-08

Task 103 (gap §6.2, super-admin Stripe management). Lets the super admin map each plan
(Free/Pro/Growth/…) to a price in the PLATFORM Stripe account, so the Billing/management
surface can connect the app's plans to the Stripe catalog. Additive + idempotent; both
default to '' so nothing changes until an operator maps a plan. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0040_plan_stripe_price"
down_revision = "0039_billing_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS stripe_price_id TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS stripe_product_id TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS stripe_price_id")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS stripe_product_id")
