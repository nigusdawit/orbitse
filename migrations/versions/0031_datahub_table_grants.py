"""datahub_table_grants — per-table data-access grants for normal admins.

Revision ID: 0031_datahub_table_grants
Revises: 0030_admin_appearance_ext
Create Date: 2026-06-03

Task 085 — client self-service analytics over the Datahub, default-DENY.

A normal client admin (admin_role != 'super_admin') gets ZERO Datahub access
until a super-admin grants specific (connection_id, table_name) pairs here.
Super-admins are never restricted by this table (their access is unconditional
in code). One row authorizes one table on one connection for one tenant. A row
whose table_name is the literal '*' grants ALL tables on that connection (a
super-admin shortcut). connection_id 0 = the platform's own database (the app
DB) — so even the app DB is grant-gated for normal admins under this model.

Shape mirrors the migration-managed `content_assets` (0027) pattern: a single
hand-written op.execute() with IF NOT EXISTS so it is idempotent, a precise
downgrade() that drops the table, and a tenant_id FK to tenants(id) with ON
DELETE CASCADE so revoking a tenant removes its grants. NOT added to the frozen
in-code init_db() DDL — Alembic owns all post-0030 schema (per the plan).
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0031_datahub_table_grants"
down_revision = "0030_admin_appearance_ext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent CREATE — re-running the migration (or a deploy that already
    # applied it out-of-band) is a no-op. UNIQUE(tenant_id, connection_id,
    # table_name) makes "grant a table" a safe ON CONFLICT DO NOTHING upsert and
    # makes the '*' shortcut a single, deduped row per connection.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS datahub_table_grants (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1
                          REFERENCES tenants(id) ON DELETE CASCADE,
            connection_id INTEGER NOT NULL,
            table_name    TEXT    NOT NULL,
            note          TEXT    NOT NULL DEFAULT '',
            granted_at    TIMESTAMP DEFAULT NOW(),
            UNIQUE (tenant_id, connection_id, table_name)
        );
        """
    )
    # Lookup index for the hot path: _dh_allowed_tables() reads all grants for
    # one (tenant_id, connection_id) on every normal-admin inspect/query call.
    op.execute(
        "CREATE INDEX IF NOT EXISTS datahub_table_grants_tenant_conn_idx "
        "ON datahub_table_grants (tenant_id, connection_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS datahub_table_grants")
