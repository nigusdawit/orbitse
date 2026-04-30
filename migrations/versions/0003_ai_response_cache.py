"""ai_response_cache — semantic cache for the visitor concierge.

Revision ID: 0003_ai_response_cache
Revises: 0002_super_admin_audit
Create Date: 2026-04-30

Stores embeddings + text for past visitor questions and the AI's reply,
so repeat / near-duplicate questions can return the cached answer
instead of paying for another Anthropic/OpenAI completion AND another
ElevenLabs TTS render (the existing TTS hash-cache in storage.py
already keys MP3s by text-hash, so reusing the same response_text
automatically reuses the same MP3 — that's the "save the asset that
already cost money" half of the design).

Schema decisions
----------------
- pgvector EXTENSION required.  Replit Postgres ships it; the call is
  guarded with IF NOT EXISTS so re-running the migration is safe and
  the migration fails loudly on databases that don't have it (which
  is the right outcome — the cache is unusable without it).
- `query_embedding VECTOR(1536)` matches OpenAI `text-embedding-3-small`.
  If we ever swap embedding providers we'll create a new column rather
  than try to convert dimensions in place.
- `content_version` lets us mass-invalidate cache entries when the
  underlying site content / system prompt changes (admin edits the
  business hours, prices, system prompt, etc.) — we just bump
  chatbot_settings.cache_content_version and read-side filters out
  rows with an older version.  Old rows are kept around so the admin
  can see "this used to be cached but is now stale" in the UI; a
  manual Purge button removes them.
- IVFFlat index for fast cosine search.  Lists=100 is a sane default
  for tables up to ~100k rows; we can REINDEX with a larger lists
  later without a schema change.

Schema mirrors the SERIAL-PK convention used by every other legacy
init_db() table (see chat_messages, super_admin_audit) — psycopg2 +
hand-written SQL throughout, no ORM.
"""

from alembic import op


revision = "0003_ai_response_cache"
down_revision = "0002_super_admin_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector — fails loudly if the extension isn't installed in the
    # cluster.  On Replit Postgres the extension is pre-available
    # (verified via SELECT name FROM pg_available_extensions).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_response_cache (
            id                SERIAL PRIMARY KEY,
            query_text        TEXT NOT NULL,
            query_embedding   VECTOR(1536) NOT NULL,
            response_text     TEXT NOT NULL,
            hit_count         INTEGER NOT NULL DEFAULT 0,
            last_hit_at       TIMESTAMPTZ,
            source_message_id INTEGER,
            content_version   INTEGER NOT NULL DEFAULT 1,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Cosine-distance approximate index.  Use the `vector_cosine_ops`
    # operator class so the `<=>` operator picks it up.  Lists=100 is
    # a fine starting point; pgvector docs recommend rows / 1000 once
    # the table is large.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_response_cache_embedding
        ON ai_response_cache USING ivfflat (query_embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    # Secondary index for the admin "top entries by hit count" listing.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_response_cache_admin
        ON ai_response_cache (content_version, hit_count DESC, last_hit_at DESC)
        """
    )

    # Per-tenant tunables live on the chatbot_settings singleton (id=1)
    # alongside system_prompt, agent_scope_tightness, etc.  IF NOT EXISTS
    # so the migration re-runs cleanly.
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_threshold REAL NOT NULL DEFAULT 0.93"
    )
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_content_version INTEGER NOT NULL DEFAULT 1"
    )
    # Lifetime counters so the admin UI can show "you've saved $X /
    # N TTS-minutes since cache went live" without rescanning every
    # cache row on each dashboard load.
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_total_hits BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_tokens_saved BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE chatbot_settings "
        "ADD COLUMN IF NOT EXISTS cache_tts_chars_saved BIGINT NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ai_response_cache_admin")
    op.execute("DROP INDEX IF EXISTS idx_ai_response_cache_embedding")
    op.execute("DROP TABLE IF EXISTS ai_response_cache")
    # Leave the chatbot_settings columns and the vector extension alone
    # on downgrade — they're harmless if unused and dropping them risks
    # losing other data that depends on the same migration boundary.
