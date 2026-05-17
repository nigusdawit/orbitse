"""merge_rag_heads — collapse the two parallel 0005 RAG branches.

Revision ID: 0006_merge_rag_heads
Revises: 0005_admin_chat_rag, 0005_rag_knowledge_base
Create Date: 2026-05-17

Two RAG-related migrations were authored on parallel branches and both
landed with a 0005_ prefix, leaving Alembic with multiple heads. This
empty merge revision joins them so `alembic upgrade head` resolves to a
single linear chain again. No DDL — both upstream migrations already
created their own tables.
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


revision = "0006_merge_rag_heads"
down_revision = ("0005_admin_chat_rag", "0005_rag_knowledge_base")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
