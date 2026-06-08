"""admin_users_rbac — multi-user admin accounts + invites (gap §6.3, RBAC Phase 1).

Revision ID: 0041_admin_users_rbac
Revises: 0040_plan_stripe_price
Create Date: 2026-06-08

Adds per-user admin accounts so the single ADMIN_PASSWORD is no longer the only way in.
- admin_users: one row per invited/active admin, with a werkzeug password hash + a role
  (super_admin | admin | editor) + status (invited | active | disabled).
- admin_invites: a single-use, expiring invite. We store only a SHA-256 HASH of the token
  (the raw token lives only in the emailed/copied link), so a DB leak can't be replayed.

Additive + idempotent. The tables start EMPTY — the owner still logs in with ADMIN_PASSWORD
(the break-glass super-admin, never stored here) and invites users from the Team & Roles tab.
Nothing about the existing login changes until a user is invited. Round-trips.
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0041_admin_users_rbac"
down_revision = "0040_plan_stripe_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER     NOT NULL DEFAULT 1,
            email         TEXT        NOT NULL,
            name          TEXT        NOT NULL DEFAULT '',
            password_hash TEXT        NOT NULL DEFAULT '',
            role          VARCHAR(20) NOT NULL DEFAULT 'admin',
            status        VARCHAR(20) NOT NULL DEFAULT 'invited',
            invited_by    BIGINT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ,
            UNIQUE (tenant_id, email)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_invites (
            id         BIGSERIAL PRIMARY KEY,
            tenant_id  INTEGER     NOT NULL DEFAULT 1,
            user_id    BIGINT      NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
            token_hash TEXT        NOT NULL,
            role       VARCHAR(20) NOT NULL DEFAULT 'admin',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_admin_invites_token ON admin_invites (token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_admin_users_email ON admin_users (tenant_id, email)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_invites")
    op.execute("DROP TABLE IF EXISTS admin_users")
