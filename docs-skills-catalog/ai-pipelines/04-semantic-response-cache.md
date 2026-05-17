# Semantic Response Cache

**Category:** AI / LLM Pipelines

## When to use
A high-traffic chat endpoint answers the same questions in slightly
different wordings. Caching the LLM completion (and any downstream
TTS render keyed by the same text) saves both the model call and the
asset cost on the next near-duplicate question.

## Architecture
- One row per cached Q&A: `query_text`, `query_embedding VECTOR(1536)`,
  `response_text`, `hit_count`, `content_version`.
- IVFFlat cosine index on the embedding column for fast ANN search.
- Read path: embed the new question, ORDER BY `<=>` ASC LIMIT 1,
  filter by current `content_version`, return only when similarity
  ≥ admin-tunable threshold (default 0.93). Returns `None` on miss
  so the caller falls through to the live LLM.
- Write path: after a successful live answer, run cheap eligibility
  checks (`should_cache_response`) — refuse for tool-driven answers,
  command-bearing answers, presentation context, PII patterns,
  too-short replies. Embed the question and `INSERT ... ON CONFLICT
  DO NOTHING` to dedupe races.
- Hit path: bump `hit_count`, `last_hit_at`, and lifetime counters on
  the settings singleton (tokens saved, TTS chars saved) so the admin
  sees lifetime savings without rescanning rows.
- Invalidation: `content_version` integer on the settings singleton.
  Bump it whenever underlying site content or the system prompt
  changes; old rows are preserved (admin can see them) but no longer
  served.

## Data model
- `ai_response_cache (id, query_text, query_embedding VECTOR(1536),
  response_text, hit_count, last_hit_at, source_message_id,
  content_version, created_at)`.
- Indexes: IVFFlat on embedding (`vector_cosine_ops`, lists=100);
  secondary B-tree on `(content_version, hit_count DESC,
  last_hit_at DESC)` for the admin "top entries" list.
- `chatbot_settings` adds `cache_enabled BOOL`, `cache_threshold
  REAL`, `cache_content_version INT`, lifetime counters.

## API surface
- Read/write happens inside `/api/chat` — not a public endpoint.
- Admin: `/admin/api/ai-cache/stats` (GET),
  `/admin/api/ai-cache/settings` (GET/PUT),
  `/admin/api/ai-cache/entries` (GET),
  `/admin/api/ai-cache/<id>` (DELETE),
  `/admin/api/ai-cache/purge` (POST),
  `/admin/api/ai-cache/backfill` (POST),
  `/admin/api/ai-cache/bump-version` (POST).

## Key files
- `semantic_cache.py` — entire module; deliberately swallows every
  exception so a failing cache never breaks chat.
- `migrations/versions/0003_ai_response_cache.py` — schema + pgvector
  extension bootstrap.

## External deps
- PostgreSQL with `pgvector` extension (Replit Postgres ships it).
- OpenAI `text-embedding-3-small` (or any 1536-dim model — match the
  VECTOR column width).

## Pitfalls
- **Global cache + PII = leak risk.** Keep the PII heuristic
  conservative; refusing to cache a safe answer costs nothing,
  caching a leaked email costs trust. Patterns to refuse: email,
  phone, long digit runs (booking/order numbers), possessive
  phrasing ("your reservation", "my booking").
- IVFFlat needs an `ANALYZE` after the first bulk load; `lists`
  should be ≈ rows/1000 for tables > 100k rows.
- Don't cache tool-driven answers — they depend on live data
  (availability, prices) that changes.
- Threshold below ~0.90 starts returning visibly off-topic answers;
  clamp the admin UI to a sane band (0.80–0.99 here).
- `ON CONFLICT DO NOTHING` requires a unique index on
  `(query_text, content_version)` — declare it explicitly.

## Adaptation notes
- For single-tenant sites the global cache is fine. For multi-tenant,
  scope by `tenant_id` and include it in the unique index.
- The `content_version` bump pattern is much simpler than per-row
  invalidation and trivially supports rollback (decrement to revive).
- If you swap embedding providers, add a NEW vector column rather
  than reinterpreting an old one.

## Related skills
- `01-streaming-tool-call-loop.md` — the cache short-circuits this
  loop on a hit.
- `03-live-editable-system-prompts.md` — prompt edits should bump
  `content_version`.
- `../rag-voice/` — the same `(provider, voice, model, text)` hash
  cache pattern is reused for TTS asset reuse.
