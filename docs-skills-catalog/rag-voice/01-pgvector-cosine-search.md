# Pgvector Cosine Search Over Chunked Documents

**Category:** RAG · vector search
**Status:** Production

## When to use
You need semantic search over an admin-uploaded corpus (docs, past chats,
notes) without standing up a separate vector DB. You already run Postgres
and want one place to back up, one place to query, and tenant scoping
"for free" via a normal `WHERE tenant_id=` filter.

## Architecture
- `pgvector` extension installed once (`CREATE EXTENSION IF NOT EXISTS
  vector`), reused by every vector table in the app.
- One `*_chunks` table per corpus (here: `rag_chunks`, `rag_chat_turns`).
  Each row holds a 1536-dim `vector` column matching
  `text-embedding-3-small`.
- Query path: embed the user query once, then
  `ORDER BY embedding <=> %s::vector LIMIT k`. The `<=>` operator is
  cosine distance; score is computed as `1 - (embedding <=> q)` so higher
  is more similar.
- The chunk query JOINs `rag_documents` and filters on
  `d.tenant_id = %s AND d.status = 'ready'` so half-indexed / failed
  documents never bleed into results.
- Tenant scoping is enforced in the JOIN/WHERE, never in the index — the
  index is global and the planner uses the IVFFlat probes plus the
  tenant filter to narrow results.

## Data model
```sql
CREATE TABLE rag_chunks (
  id            BIGSERIAL PRIMARY KEY,
  document_id   INTEGER NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
  tenant_id     INTEGER NOT NULL DEFAULT 1,
  chunk_index   INTEGER NOT NULL,
  page_number   INTEGER,
  content_text  TEXT NOT NULL,
  token_count   INTEGER NOT NULL DEFAULT 0,
  embedding     vector(1536),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX rag_chunks_embedding_idx
  ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```
Same shape (with `session_id`, `role`, `message_id`) for `rag_chat_turns`.

> NOTE: the project notes mention HNSW in some places but the migrations
> ship IVFFlat (`lists = 100`). IVFFlat is fine up to a few hundred
> thousand vectors and rebuilds quickly; switch to HNSW only if you
> need better recall at scale.

## API surface
- `rag.retrieve(query, tenant_id, top_k)` → `[{chunk_id, document_id,
  filename, page_number, content_text, score}]`.
- `rag.format_chunks_for_prompt(chunks)` → system-block string with
  `[source: file p.N #chunk_id]` markers the LLM is told to echo back.
- `rag.get_chunk(chunk_id, tenant_id=...)` → strict tenant-scoped fetch
  for citation viewers; returns `None` cross-tenant (no IDOR).

## Key files
- `rag.py` — `retrieve`, `format_chunks_for_prompt`, `get_chunk`, helpers.
- `migrations/versions/0005_admin_chat_rag.py` — table + index DDL.
- `app.py` — admin chat loop calls `retrieve` + `format_chunks_for_prompt`
  when the per-session `use_kb` flag is on, and exposes the
  `lookup_knowledge_base` tool for explicit drill-down.

## External deps
- Postgres ≥ 13 with the `pgvector` extension.
- An embedding model (OpenAI `text-embedding-3-small`, 1536 dims). Any
  embedder works as long as every row in the table uses the same model
  and dimensions.

## Pitfalls
- Mixing models silently breaks similarity. If you ever change the
  embedder you MUST re-embed every row; a partial corpus will appear
  to work but rank nonsense at the top.
- IVFFlat needs `ANALYZE` (or enough inserts) before the planner uses
  the index. The migration creates the index empty — first queries may
  fall back to a sequential scan until rows arrive.
- The `<=>` operator returns DISTANCE, not similarity. Always wrap as
  `1 - (embedding <=> q)` when surfacing a score.
- The tenant filter MUST appear in the SQL — there is no row-level
  security. Skipping it leaks across tenants.

## Adaptation notes
- Swap embedder by changing `EMBED_MODEL` / `EMBED_DIMS` in `rag.py`
  and the `vector(N)` column type. Plan a re-embed migration.
- For larger corpora (>500k rows) move to HNSW: drop the existing
  index and `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)
  WITH (m=16, ef_construction=64)`. The retrieve query does not change.
- For per-document filters add a `WHERE document_id = ANY(%s)` clause
  before `ORDER BY`; the IVFFlat planner still uses the index.

## Related skills
- `02-document-ingest-and-chunker.md` — how rows get into `rag_chunks`.
- `03-kb-manager-ui.md` — admin upload, status, citation viewer.
- `05-cross-chat-recall.md` — same pattern over `rag_chat_turns`.
- `../ai-pipelines/01-streaming-tool-call-loop.md` — host loop that
  calls `lookup_knowledge_base` as a tool.
- `../auth/` — tenant scoping primitives the WHERE clause relies on.
