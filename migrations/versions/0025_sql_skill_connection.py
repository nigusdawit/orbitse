"""custom_sql_skills.connection_id — let a saved SQL skill target a connection.

Revision ID: 0025_sql_skill_connection
Revises: 0024_datahub_semantic_layer
Create Date: 2026-06-01

Phase 7 / Datahub (task 056). A saved SQL skill can now run against any Datahub
connection: 0 = the app's own DB (prior behavior), other ids reference
external_data_connections. Column added for existing DBs; init_db has it for
fresh forks.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0025_sql_skill_connection"
down_revision = "0024_datahub_semantic_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE custom_sql_skills "
               "ADD COLUMN IF NOT EXISTS connection_id INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE custom_sql_skills DROP COLUMN IF EXISTS connection_id")
