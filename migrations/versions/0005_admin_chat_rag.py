"""admin_chat_rag — pgvector tables for KB docs, chat-turn recall, and auto-memory.

Revision ID: 0005_admin_chat_rag
Revises: 0004_ai_cache_unique_index
Create Date: 2026-05-17

What this adds
--------------
pgvector-backed tables for the admin-chat RAG / memory feature set.

NOTE: rag_documents + rag_chunks (the uploaded-knowledge-base tables) are owned
by the sibling revision 0005_rag_knowledge_base, NOT this one — see the comment
in upgrade(). This revision originally redefined them with a conflicting schema,
which broke a fresh `alembic upgrade head`. It now creates only:

1. rag_chat_turns
   Cross-chat recall. Every persisted admin chat user/assistant turn is
   re-embedded into this table so the agent can pull in snippets from
   previous sessions when the per-session "Recall past chats" toggle is
   on. Kept SEPARATE from rag_chunks so KB retrieval and chat-history
   retrieval can run with different top-k and different filters.

2. admin_chat_memories
   ChatGPT-style auto-memory: short facts extracted from prior turns
   ("user prefers X", "their business is Y") that get injected as a
   system block on every new chat. Dedupe by content_hash so the
   extractor can run on every turn without producing duplicate rows.

Both tables use the existing tenant_id pattern (INTEGER NOT NULL
DEFAULT 1). The pgvector extension was already enabled by
0003_ai_response_cache, so we don't re-CREATE EXTENSION here — but we
guard with IF NOT EXISTS in case this migration ever runs against a
fresh DB where 0003's CREATE EXTENSION failed silently.

Index strategy
--------------
ivfflat for the chat_turn embedding column (consistent with the
existing semantic_cache index pattern). Memories are usually under
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
    # INTENTIONALLY OMITTED. rag_documents + rag_chunks are owned exclusively
    # by the sibling revision 0005_rag_knowledge_base (both 0005_* migrations
    # branched off 0004 in parallel). This revision USED to also
    # `CREATE TABLE IF NOT EXISTS` those two with a *different* schema
    # (rag_chunks WITH a tenant_id column, rag_documents with
    # error_message/source_path instead of storage_key/error_text). Because
    # both used IF NOT EXISTS, whichever branch ran first won, the other's
    # CREATE no-op'd, and then this revision's `CREATE INDEX ... (tenant_id)`
    # blew up with "column tenant_id does not exist" on a fresh DB — breaking
    # the very first import. The monolith's RAG code (rag.py) uses the
    # rag_knowledge_base schema (tenant_id + storage_key + error_text), and
    # nothing in the monolith uses the tenant_id index this revision tried to
    # add, so we let rag_knowledge_base be the single owner of those tables.
    # rag_chat_turns + admin_chat_memories below remain this revision's own.

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
    # rag_chunks + rag_documents are owned by 0005_rag_knowledge_base — that
    # revision's downgrade drops them; this one must not (it no longer creates
    # them, see upgrade()).
    # Do NOT drop the vector extension — semantic_cache + future migrations
    # depend on it. The extension is shared infra.
