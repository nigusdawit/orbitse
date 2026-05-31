# Task 035 — Visitor reliability/context (pylego) + eval seed (Phase 6 / Epic A)

**Status:** done
**Branch:** task/035-visitor-pylego
**Depends on:** 034

## Goal
Wire the generic pylego reliability (retry/fallback) + token-aware history trim
into the visitor /api/chat loop, with their own super-admin knobs, plus a visitor
eval seed. All default-off / identity.

## Acceptance criteria
- [x] Visitor knobs in config + AI Control registry (group "Visitor AI"):
      visitor_llm_max_retries, visitor_provider_fallback(+model),
      visitor_history_token_budget. Defaults inert.
- [x] Visitor round dispatch wrapped with pylego.llm_router.reliable_round
      (identity at default: 1 opener, 0 retries); optional cross-provider fallback.
- [x] Token-aware history trim on the visitor messages (budget 0 = off).
- [x] pylego/evals/visitor_ai_suite.py seed suite.

## Test requirements
- [x] Visitor /api/chat still streams 200 + logs its activity row at default
      config (identity); visitor knobs present in /admin/api/ai-control; 034
      regression green; visitor eval suite runs.

## Verification
26 pylego context/reliability unit tests; embedded-PG: visitor stream 200+events,
activity row logged, knobs present, 034 tests pass. Default = current behavior.

## Notes
Visitor already has its own per-IP chat rate limiter + the semantic_cache.py
response cache, so 035 deliberately adds only retry/fallback + history trim
(no duplicate rate limit / response cache). Fail-open throughout.
