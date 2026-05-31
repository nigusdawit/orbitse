# Task 028 — pylego Smarter context (Admin AI)

**Status:** done
**Branch:** task/028-pylego-context
**Depends on:** 027

## Goal

Token-aware history trimming + an opt-in semantic response cache for the Admin
AI — both strictly additive (inert at default config). Plan: `PLAN_ADMIN_AI.md`.

## Acceptance criteria

- [x] `pylego/history.py`: `trim_to_budget(messages, budget, model)` — drops
      oldest prior turns to fit a token budget; keeps system prompt + current
      turn; never orphans a `tool` message; budget<=0 = identity; fail-open.
      tiktoken when available, chars/4 fallback.
- [x] `pylego/respcache.py`: `ResponseCache` (embed question, store answer text)
      + `InMemoryStore` (cosine); threshold-clamped; content-version isolation;
      PII-guarded; disabled by default; fail-open.
- [x] Wired into the admin loop: trim before the round loop; cache LOOKUP before
      loop (serve + skip LLM on hit); cache STORE after loop ONLY when the turn
      used NO tools — so data-dependent answers are never cached / never stale.
- [x] All config defaults inert (budget 0, cache off).

## Test requirements

- [x] `tests/test_pylego_context.py` — trim identity/already-fits/drops-oldest/
      no-orphan-tool/token-estimate; cache disabled-noop/hit/miss/PII-skip/
      version-isolation/threshold-clamp/embed-fail-open.
- [x] Embedded-PG boot: default stream unchanged; trim+cache ON → stream still
      works (fail-open on missing embed key).

## Verification

35/35 pylego unit tests; pyflakes clean; `_ctx_boot.py` PASS.

## Drift reason

Response cache is wired in the SAFE "store-only-if-no-tools" mode (rather than a
naive cache-everything), because admin answers are often data-dependent and a
stale hit would be a correctness regression — which the "only enhance, never
disturb" mandate forbids. By construction the cache only ever serves static /
how-to answers. In-memory store for now (per-worker); a cross-worker pgvector
store is a future swap-in behind the same interface.

## Notes

tiktoken is optional — trim falls back to a chars/4 heuristic when it's absent,
so it adds no hard dependency. Cache lookup costs one embedding call per turn
when enabled (default off).
