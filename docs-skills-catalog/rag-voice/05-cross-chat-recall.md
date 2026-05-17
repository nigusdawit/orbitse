# Cross-Chat Semantic Recall

**Category:** RAG · memory
**Status:** Schema landed · embed-on-write and `lookup_past_conversations` not yet wired

> The `rag_chat_turns` table (with its partial UNIQUE index and IVFFlat
> embedding index) is in place via migration `0005_admin_chat_rag`.
> The per-turn embed worker, the `recall_past_turns` helper, and the
> `lookup_past_conversations` tool described below are planned and
> not yet implemented in `app.py` at the time of writing. Treat this
> file as a blueprint for the missing pieces.

## When to use
You want the assistant to be able to say *"as we discussed two weeks
ago in your billing thread, …"* — pulling in snippets from past
conversations the user had on a different day. Different problem from
auto-memory (which compresses to facts); here you want the actual
prior turn text, retrieved by similarity.

## Architecture
- **Write side.** Every persisted admin chat user/assistant turn is
  embedded into `rag_chat_turns` with `(session_id, message_id, role,
  content_text, embedding, session_title)`. `session_title` is
  snapshotted at write time so retrieval can render
  `"[from chat: <title>, <date>]"` without joining back to the
  sessions table.
- **Idempotency.** A partial UNIQUE index
  `(session_id, message_id) WHERE message_id IS NOT NULL` lets the
  per-message embed worker be retried safely (`INSERT … ON CONFLICT
  DO NOTHING`).
- **Read side.** Per-session toggle `use_recall` (mirroring `use_kb`)
  gates auto-injection. When on, embed the user query, take top K
  (typically 4) nearest turns across the tenant's full chat history,
  exclude the current session, and inject them as a system block with
  `[recall: chat-title — YYYY-MM-DD]` markers.
- The AI can also explicitly call `lookup_past_conversations(query,
  top_k)` as an OpenAI tool when it wants to drill down. Same retrieval
  helper, narrower call site.

## Data model
```sql
CREATE TABLE rag_chat_turns (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     INTEGER NOT NULL DEFAULT 1,
  session_id    TEXT NOT NULL,
  message_id    INTEGER,                  -- nullable for legacy rows
  role          TEXT NOT NULL,            -- 'user' | 'assistant'
  content_text  TEXT NOT NULL,
  token_count   INTEGER NOT NULL DEFAULT 0,
  embedding     vector(1536),
  session_title TEXT DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX rag_chat_turns_msg_uidx
  ON rag_chat_turns (session_id, message_id) WHERE message_id IS NOT NULL;
CREATE INDEX rag_chat_turns_embedding_idx
  ON rag_chat_turns USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

Kept deliberately separate from `rag_chunks` so KB retrieval and
chat-history retrieval can run with different `top_k`, different time
filters, and different prompt headers.

## API surface
- Internal helper (e.g. `recall_past_turns(query, tenant_id, top_k,
  exclude_session_id)`). Same shape as `rag.retrieve` but joins
  `session_title` and excludes the current session.
- Optional tool definition exposed to the model:
  `lookup_past_conversations(query, top_k=4)`.

## Key files
- `migrations/versions/0005_admin_chat_rag.py`
- `app.py` — embed-on-write hook in the chat persistence path; recall
  helper called from the chat loop alongside KB retrieval.

## External deps
Same as `01-pgvector-cosine-search.md`.

## Pitfalls
- **Always exclude the current session** from recall results, or the
  assistant ends up "remembering" the message it just received and
  parroting it back.
- **Recency vs similarity.** Pure cosine ranks an old highly-relevant
  turn above a slightly-relevant recent one. Consider a recency boost
  (`score - λ * age_days`) for chatty users.
- **Privacy.** A recall hit can surface a sentence the user wrote a
  month ago in front of someone glancing at the screen now. Render
  recall snippets behind a collapsible pill rather than inline.
- **Embed cost on every turn.** Skip turns shorter than ~5 tokens
  ("ok", "thanks") to keep cost down.
- **Tenant filter is mandatory** — same as KB chunks.

## Adaptation notes
- Public/visitor chat recall: add a `visitor_id` column and filter on
  it instead of `tenant_id`.
- Time-bounded recall: add an `AND created_at > NOW() - INTERVAL '90
  days'` clause; the IVFFlat index still handles the search and the
  date predicate prunes after.
- Compress before recall: combine with `04-auto-memory.md` — extract
  facts from old turns, drop the raw turn embeddings after N days.

## Related skills
- `01-pgvector-cosine-search.md` — same pattern, different table.
- `04-auto-memory.md` — orthogonal memory strategy (compressed facts).
- `../ai-pipelines/01-streaming-tool-call-loop.md` — host loop that
  exposes `lookup_past_conversations` as a tool.
