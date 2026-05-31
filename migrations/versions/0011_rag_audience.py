"""rag_audience — scope each KB document to an AI audience (visitor|admin|both).

Revision ID: 0011_rag_audience
Revises: 0010_activity_surface
Create Date: 2026-05-31

Phase 6 / Epic B. rag.retrieve() can now filter documents by audience so the
super admin can say "this doc is for the visitor concierge only / the admin AI
only / both". Existing docs default to 'both' (unchanged behavior). rag_documents
is owned by the Alembic chain (created in 0005_rag_knowledge_base), so the column
is added here; a fresh fork runs the full chain at boot.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0011_rag_audience"
down_revision = "0010_activity_surface"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE rag_documents "
        "ADD COLUMN IF NOT EXISTS audience TEXT NOT NULL DEFAULT 'both'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE rag_documents DROP COLUMN IF EXISTS audience")
