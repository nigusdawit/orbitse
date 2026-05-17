"""rag_knowledge_base — admin-chat RAG over uploaded documents.

Revision ID: 0005_rag_knowledge_base
Revises: 0004_ai_cache_unique_index
Create Date: 2026-05-17

Task #79: admin chat needs a true vector-search RAG layer so admins can
upload PDFs/CSVs/TXT/DOCX/PPTX and have the AI pull relevant chunks
into context automatically. The pgvector extension is already enabled
by migration 0003 (ai_response_cache), so we just declare two new
tables, an HNSW cosine index on the chunk embeddings, a per-session
toggle column on admin_chat_sessions, and a price row for
text-embedding-3-small so cost reporting works on day one.

Why HNSW (not IVFFlat like 0003)?
---------------------------------
HNSW gives better recall on a small-medium corpus (a few hundred docs
chunked into a few thousand rows) WITHOUT needing a separate training
step. IVFFlat needs `lists` tuned to row count and a REINDEX after
bulk loads. For an admin-uploaded knowledge base where rows trickle
in over time, HNSW is the simpler operational story. Requires
pgvector >= 0.5.0 — available on Replit Postgres and any modern
managed cluster.
"""

from alembic import op


revision = "0005_rag_knowledge_base"
down_revision = "0004_ai_cache_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector — guarded, since migration 0003 already enabled it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # One row per uploaded document. `source_mtime` carries the
    # filesystem (or S3 ETag-style) timestamp of the underlying file so
    # the nightly reindex tick can detect when an admin re-uploads or
    # edits a file in-place and re-embed without manual action.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_documents (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            filename      VARCHAR(300) NOT NULL,
            storage_key   VARCHAR(400) NOT NULL DEFAULT '',
            mime          VARCHAR(120) NOT NULL DEFAULT '',
            size_bytes    BIGINT NOT NULL DEFAULT 0,
            page_count    INTEGER NOT NULL DEFAULT 0,
            chunk_count   INTEGER NOT NULL DEFAULT 0,
            token_count   INTEGER NOT NULL DEFAULT 0,
            status        VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_text    TEXT NOT NULL DEFAULT '',
            indexed_at    TIMESTAMPTZ,
            source_mtime  DOUBLE PRECISION,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_documents_tenant_recent
            ON rag_documents (tenant_id, created_at DESC)
        """
    )

    # One row per ~800-token chunk. ON DELETE CASCADE so deleting a
    # document automatically prunes its chunks (no orphan vectors).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id            SERIAL PRIMARY KEY,
            document_id   INTEGER NOT NULL
                          REFERENCES rag_documents(id) ON DELETE CASCADE,
            chunk_index   INTEGER NOT NULL DEFAULT 0,
            page_number   INTEGER,
            content_text  TEXT NOT NULL DEFAULT '',
            token_count   INTEGER NOT NULL DEFAULT 0,
            embedding     VECTOR(1536) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc
            ON rag_chunks (document_id, chunk_index)
        """
    )
    # HNSW cosine index for fast top-K retrieval. m + ef_construction
    # left at defaults (16, 64) — fine for tens of thousands of chunks.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
            ON rag_chunks USING hnsw (embedding vector_cosine_ops)
        """
    )

    # Per-session toggle for the admin chat. NULL means "use the global
    # default" (which today is ON); the chat loop reads this via
    # _admin_chat_get_or_create_session and skips retrieval when false.
    op.execute(
        "ALTER TABLE admin_chat_sessions "
        "ADD COLUMN IF NOT EXISTS use_kb BOOLEAN NOT NULL DEFAULT TRUE"
    )

    # Seed embedding-model price so api_cost_events can stamp a real
    # cost per rag_embed call. OpenAI's text-embedding-3-small list
    # price is $0.02 per 1M tokens (2025); we re-use the existing
    # input_price_per_million_tokens column for that — embeddings have
    # no separate output side.
    op.execute(
        """
        INSERT INTO model_prices
          (provider, model, surface,
           input_price_per_million_tokens, notes)
        VALUES
          ('openai', 'text-embedding-3-small', 'rag_embed',
           0.020, 'OpenAI text-embedding-3-small list price (2025)')
        ON CONFLICT (provider, model, surface) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rag_chunks_embedding")
    op.execute("DROP INDEX IF EXISTS idx_rag_chunks_doc")
    op.execute("DROP TABLE IF EXISTS rag_chunks")
    op.execute("DROP INDEX IF EXISTS idx_rag_documents_tenant_recent")
    op.execute("DROP TABLE IF EXISTS rag_documents")
    op.execute(
        "ALTER TABLE admin_chat_sessions DROP COLUMN IF EXISTS use_kb"
    )
    # Leave the model_prices seed row in place — harmless if unused.
