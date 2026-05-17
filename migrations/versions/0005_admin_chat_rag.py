"""admin_chat_rag — pgvector tables for KB docs, chat-turn recall, and auto-memory.

Revision ID: 0005_admin_chat_rag
Revises: 0004_ai_cache_unique_index
Create Date: 2026-05-17

What this adds
--------------
Three pgvector-backed tables that together power the admin-chat RAG /
memory feature set:

1. rag_documents + rag_chunks
   Knowledge-base files the admin uploads (PDF / DOCX / PPTX / CSV /
   TXT). One row per source file in rag_documents, N rows per file in
   rag_chunks (each chunk has its own 1536-dim embedding from
   text-embedding-3-small).

2. rag_chat_turns
   Cross-chat recall. Every persisted admin chat user/assistant turn is
   re-embedded into this table so the agent can pull in snippets from
   previous sessions when the per-session "Recall past chats" toggle is
   on. Kept SEPARATE from rag_chunks so KB retrieval and chat-history
   retrieval can run with different top-k and different filters.

3. admin_chat_memories
   ChatGPT-style auto-memory: short facts extracted from prior turns
   ("user prefers X", "their business is Y") that get injected as a
   system block on every new chat. Dedupe by content_hash so the
   extractor can run on every turn without producing duplicate rows.

All three tables use the existing tenant_id pattern (INTEGER NOT NULL
DEFAULT 1, FK to tenants). The pgvector extension was already enabled
by 0003_ai_response_cache, so we don't re-CREATE EXTENSION here — but
we guard with IF NOT EXISTS in case this migration ever runs against a
fresh DB where 0003's CREATE EXTENSION failed silently.

Index strategy
--------------
ivfflat for the chunk + chat_turn embedding columns (consistent with
the existing semantic_cache index pattern). Memories are usually under
1000 rows so a plain b-tree on (tenant_id, last_used_at) is enough; we
order memory injection by recency × relevance in Python, not in SQL.
"""

from __future__ import annotations

from alembic import op


revision = "0005_admin_chat_rag"
down_revision = "0004_ai_cache_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive — 0003 already created this, but a fresh DB rerunning
    # all migrations doesn't hurt.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- 1. Knowledge-base documents + chunks --------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_documents (
            id              SERIAL      PRIMARY KEY,
            tenant_id       INTEGER     NOT NULL DEFAULT 1
                                        REFERENCES tenants(id) ON DELETE CASCADE,
            filename        TEXT        NOT NULL,
            mime            TEXT        NOT NULL DEFAULT '',
            size_bytes      BIGINT      NOT NULL DEFAULT 0,
            page_count      INTEGER     NOT NULL DEFAULT 0,
            chunk_count     INTEGER     NOT NULL DEFAULT 0,
            status          TEXT        NOT NULL DEFAULT 'indexing',
                            -- 'indexing' | 'ready' | 'failed'
            error_message   TEXT        DEFAULT NULL,
            source_path     TEXT        DEFAULT NULL,
            source_mtime    DOUBLE PRECISION DEFAULT NULL,
            indexed_at      TIMESTAMPTZ DEFAULT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rag_documents_tenant_idx "
        "ON rag_documents (tenant_id, created_at DESC);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id              BIGSERIAL   PRIMARY KEY,
            document_id     INTEGER     NOT NULL
                                        REFERENCES rag_documents(id) ON DELETE CASCADE,
            tenant_id       INTEGER     NOT NULL DEFAULT 1,
            chunk_index     INTEGER     NOT NULL,
            page_number     INTEGER     DEFAULT NULL,
            content_text    TEXT        NOT NULL,
            token_count     INTEGER     NOT NULL DEFAULT 0,
            embedding       vector(1536),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rag_chunks_doc_idx "
        "ON rag_chunks (document_id, chunk_index);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rag_chunks_tenant_idx "
        "ON rag_chunks (tenant_id);"
    )
    # IVFFlat cosine index — matches the semantic_cache pattern (lists=100
    # is a fine starting point for our expected corpus size of a few
    # thousand chunks; pgvector recommends sqrt(rows) once you scale).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class WHERE relname = 'rag_chunks_embedding_idx'
            ) THEN
                CREATE INDEX rag_chunks_embedding_idx
                    ON rag_chunks
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
            END IF;
        END$$;
        """
    )

    # ---- 2. Chat-turn recall (cross-chat semantic memory) --------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_chat_turns (
            id              BIGSERIAL   PRIMARY KEY,
            tenant_id       INTEGER     NOT NULL DEFAULT 1,
            session_id      TEXT        NOT NULL,
            message_id      INTEGER     DEFAULT NULL,
                            -- admin_chat_messages.id when known; nullable
                            -- because some legacy rows have no surrogate id
            role            TEXT        NOT NULL,
                            -- 'user' | 'assistant'
            content_text    TEXT        NOT NULL,
            token_count     INTEGER     NOT NULL DEFAULT 0,
            embedding       vector(1536),
            session_title   TEXT        DEFAULT '',
                            -- snapshotted at write time so retrieval can
                            -- render "[from chat: <title>, <date>]" without
                            -- a second join
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rag_chat_turns_session_idx "
        "ON rag_chat_turns (session_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS rag_chat_turns_tenant_idx "
        "ON rag_chat_turns (tenant_id, created_at DESC);"
    )
    op.execute(
        # Idempotency for the per-message embed worker — same (session,
        # message_id) re-embed is a no-op via ON CONFLICT.
        "CREATE UNIQUE INDEX IF NOT EXISTS rag_chat_turns_msg_uidx "
        "ON rag_chat_turns (session_id, message_id) "
        "WHERE message_id IS NOT NULL;"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class WHERE relname = 'rag_chat_turns_embedding_idx'
            ) THEN
                CREATE INDEX rag_chat_turns_embedding_idx
                    ON rag_chat_turns
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
            END IF;
        END$$;
        """
    )

    # ---- 3. Auto-memory ------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_chat_memories (
            id              SERIAL      PRIMARY KEY,
            tenant_id       INTEGER     NOT NULL DEFAULT 1
                                        REFERENCES tenants(id) ON DELETE CASCADE,
            content         TEXT        NOT NULL,
                            -- short fact, e.g. "User runs a coffee shop in Lisbon"
            content_hash    TEXT        NOT NULL,
                            -- sha256 of normalized content — dedupe key
            source_session_id TEXT      DEFAULT NULL,
                            -- where the fact was first extracted from
            source_message_id INTEGER   DEFAULT NULL,
            confidence      REAL        NOT NULL DEFAULT 0.5,
            use_count       INTEGER     NOT NULL DEFAULT 0,
            last_used_at    TIMESTAMPTZ DEFAULT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS admin_chat_memories_dedupe_uidx "
        "ON admin_chat_memories (tenant_id, content_hash);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS admin_chat_memories_recency_idx "
        "ON admin_chat_memories (tenant_id, last_used_at DESC NULLS LAST, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_chat_memories;")
    op.execute("DROP TABLE IF EXISTS rag_chat_turns;")
    op.execute("DROP TABLE IF EXISTS rag_chunks;")
    op.execute("DROP TABLE IF EXISTS rag_documents;")
    # Do NOT drop the vector extension — semantic_cache + future migrations
    # depend on it. The extension is shared infra.
