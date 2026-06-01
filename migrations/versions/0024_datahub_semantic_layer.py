"""datahub semantic layer — table/column/relationship/example annotations.

Revision ID: 0024_datahub_semantic_layer
Revises: 0023_neutralize_default_copy
Create Date: 2026-06-01

Phase 7 / Datahub (task 053). Stores human + AI descriptions of a data source's
schema so the Business Assistant writes correct SQL. connection_id 0 = the app's
own database; any other id references an external_data_connections row.
ai_generated/reviewed power the "AI drafts, super-admin corrects" workflow.
Mirrors the CREATE TABLE statements in init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0024_datahub_semantic_layer"
down_revision = "0023_neutralize_default_copy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS db_table_annotations (
            id            BIGSERIAL PRIMARY KEY,
            connection_id INTEGER NOT NULL DEFAULT 0,
            table_name    TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            is_sensitive  BOOLEAN NOT NULL DEFAULT FALSE,
            ai_generated  BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed      BOOLEAN NOT NULL DEFAULT FALSE,
            updated_by    TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (connection_id, table_name)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS db_column_annotations (
            id            BIGSERIAL PRIMARY KEY,
            connection_id INTEGER NOT NULL DEFAULT 0,
            table_name    TEXT NOT NULL,
            column_name   TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            semantic_type TEXT NOT NULL DEFAULT '',
            is_sensitive  BOOLEAN NOT NULL DEFAULT FALSE,
            sample_values JSONB NOT NULL DEFAULT '[]'::jsonb,
            ai_generated  BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed      BOOLEAN NOT NULL DEFAULT FALSE,
            updated_by    TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (connection_id, table_name, column_name)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_dh_cols "
               "ON db_column_annotations (connection_id, table_name)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS db_relationships (
            id            BIGSERIAL PRIMARY KEY,
            connection_id INTEGER NOT NULL DEFAULT 0,
            from_table    TEXT NOT NULL,
            from_column   TEXT NOT NULL,
            to_table      TEXT NOT NULL,
            to_column     TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            ai_generated  BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (connection_id, from_table, from_column, to_table, to_column)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS db_query_examples (
            id            BIGSERIAL PRIMARY KEY,
            connection_id INTEGER NOT NULL DEFAULT 0,
            question      TEXT NOT NULL DEFAULT '',
            sql           TEXT NOT NULL DEFAULT '',
            notes         TEXT NOT NULL DEFAULT '',
            ai_generated  BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_dh_examples "
               "ON db_query_examples (connection_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS db_query_examples")
    op.execute("DROP TABLE IF EXISTS db_relationships")
    op.execute("DROP TABLE IF EXISTS db_column_annotations")
    op.execute("DROP TABLE IF EXISTS db_table_annotations")
