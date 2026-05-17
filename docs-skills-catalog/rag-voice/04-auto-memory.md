# Auto-Extracted Long-Term Memories

**Category:** RAG · memory
**Status:** Schema landed · extractor not yet wired

> The `admin_chat_memories` table and its dedupe index are in place
> (migration `0005_admin_chat_rag`). The end-of-turn extractor and
> the per-turn injection block described below are planned but not
> yet implemented in `app.py` at the time of writing. Treat this file
> as a blueprint for the missing pieces, not as a description of
> currently-running code.

## When to use
You want a ChatGPT-style "the assistant remembers things about me"
behaviour for an admin chat — short facts like "user runs a coffee shop
in Lisbon" injected on every new session — without re-reading the
entire chat history on every turn.

## Architecture
1. **Extractor.** After each persisted assistant turn, fire a cheap
   LLM call (`gpt-4o-mini` in JSON mode) with the last user + assistant
   messages and a system prompt that asks: "Return an array of short,
   factual, durable facts about the user. No opinions, no transient
   state." Output schema is `{"memories": [{"content": str,
   "confidence": float}]}`.
2. **Dedupe at write time.** `content_hash = sha256(normalize(content))`
   with a `UNIQUE (tenant_id, content_hash)` index, so the extractor
   can run on every turn without growing duplicates. `INSERT … ON
   CONFLICT (tenant_id, content_hash) DO UPDATE SET use_count =
   use_count + 1, last_used_at = NOW()`.
3. **Injection.** At the top of each new chat turn, select the top N
   memories ordered by `last_used_at DESC NULLS LAST, created_at DESC,
   confidence DESC` and prepend them as a single system block:
   `"Things you remember about this user: …"`. N is small (typically
   20) so token cost is constant regardless of how many memories exist.

## Data model
```sql
CREATE TABLE admin_chat_memories (
  id                 SERIAL PRIMARY KEY,
  tenant_id          INTEGER NOT NULL DEFAULT 1
                     REFERENCES tenants(id) ON DELETE CASCADE,
  content            TEXT NOT NULL,
  content_hash       TEXT NOT NULL,
  source_session_id  TEXT,
  source_message_id  INTEGER,
  confidence         REAL NOT NULL DEFAULT 0.5,
  use_count          INTEGER NOT NULL DEFAULT 0,
  last_used_at       TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX admin_chat_memories_dedupe_uidx
  ON admin_chat_memories (tenant_id, content_hash);
CREATE INDEX admin_chat_memories_recency_idx
  ON admin_chat_memories (tenant_id, last_used_at DESC NULLS LAST, created_at DESC);
```

## API surface
- Internal helper called from the chat persistence path — no public
  HTTP route. An admin "Memories" tab can be wired with simple CRUD
  (`GET /admin/api/memories`, `DELETE /admin/api/memories/<id>`) if
  the UX calls for it.
- Use `ON CONFLICT` dedupe so the extractor is safe to call from any
  worker.

## Key files
- `migrations/versions/0005_admin_chat_rag.py` — table + indexes.
- `app.py` — extractor call site (around the assistant-message persist),
  injection block at chat-loop start.

## External deps
- Any cheap JSON-mode LLM. `gpt-4o-mini` works well; budget ~200 tokens
  per extraction.

## Pitfalls
- **Don't extract every token.** Run the extractor at end-of-turn
  (after the assistant message is committed), not on partial streams.
- **Watch for PII / false confidence.** The extractor will gladly
  invent "user lives at 42 Acacia Ave." — pin its system prompt with
  examples, and cap `confidence` to a sane default. Consider a
  visible "Forget this" button per memory.
- **`content_hash` MUST normalize.** Lowercase, strip punctuation +
  collapse whitespace before hashing or "User likes coffee." and
  "user likes coffee" produce two rows.
- **Cross-tenant leak risk** is identical to KB chunks: every read
  must filter by `tenant_id`. The dedupe UNIQUE covers writes.
- **No vector search by default.** Memories are pulled by recency, not
  semantics. If you want "memories relevant to this question" instead,
  add an `embedding vector(1536)` column and re-use the cosine pattern
  from `01-pgvector-cosine-search.md`.

## Adaptation notes
- Per-user memories (instead of per-tenant): add `user_id INTEGER` to
  the table + UNIQUE index and filter on it at read time.
- Memory expiry: add `expires_at TIMESTAMPTZ` and an
  `AND (expires_at IS NULL OR expires_at > NOW())` clause on the read.
- Confidence decay: subtract a small amount from `confidence` each
  week the memory isn't used; prune below a threshold.

## Related skills
- `05-cross-chat-recall.md` — orthogonal: full prior-turn snippets
  retrieved by semantic similarity instead of compressed facts.
- `../ai-pipelines/03-live-editable-system-prompts.md` — where the
  injected memory block lives in the final prompt assembly.
