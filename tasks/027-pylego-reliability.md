# Task 027 — pylego Reliability (Admin AI)

**Status:** done
**Branch:** task/027-pylego-reliability
**Depends on:** 026

## Goal

Add reliability to the Admin AI LLM path: bounded retry + provider fallback on
transient stream-open failures, an opt-in OpenAI call timeout, and a rate limit
for busy clients — all strictly additive (inert at default config). Plan:
`PLAN_ADMIN_AI.md`.

## Acceptance criteria

- [x] `pylego/llm_router.py`: `reliable_round(openers, max_retries)` — retries the
      primary on TRANSIENT errors before the first event, falls back to other
      openers, commits once streaming starts. Identity when one opener + 0 retries.
- [x] `pylego/ratelimit.py`: fixed-window limiter; MemoryStore + lazy-table
      PostgresStore (cluster-wide); `enabled=False` default; FAILS OPEN on store error.
- [x] Wired: admin round dispatch builds openers + wraps with `reliable_round`
      (default = single opener, 0 retries = prior behavior); fallback only when
      `ADMIN_CHAT_PROVIDER_FALLBACK` + `ADMIN_CHAT_FALLBACK_MODEL` + other client set.
- [x] Opt-in OpenAI streaming timeout in `_stream_round_openai` (default 0 = SDK default).
- [x] Per-session rate-limit gate on `/admin/api/chat/send` + `/stream` (default off).
- [x] Config defaults all INERT (timeout 0, retries 0, fallback off, limiter off).

## Test requirements

- [x] `tests/test_pylego_reliability.py` — identity, transient-retry, no-retry-on-
      fatal, fallback, no-retry-after-commit, transient classification; limiter
      allow/block/disabled/fail-open/per-key.
- [x] Embedded-PG boot: default config stream works (identity); limiter ON → flood
      429s; Postgres store table created + counted.

## Verification

23/23 pylego unit tests; pyflakes clean; `_rel_boot.py` PASS (default identity,
429 on flood, postgres store counted).

## Drift reason

Config defaults set to fully INERT (was tempted to default timeout=60/retries=2)
— honoring the user's "only enhance, never disturb" mandate: reliability is one
env var away but ships off so current behavior is byte-identical.

## Notes

Cross-provider fallback requires an explicit `ADMIN_CHAT_FALLBACK_MODEL` (the
fallback provider needs a model name). Retry/fallback act ONLY before the first
streamed token (can't un-send tokens) — by design. OpenAI timeout applies to all
`_stream_round_openai` callers (admin + visitor) when set; default 0 = no change.
