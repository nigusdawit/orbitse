# Task 030 — AI Control settings backend (Phase 5)

**Status:** done
**Branch:** task/030-ai-control-settings
**Depends on:** 026–029 (pylego)

## Goal
DB-backed, super-admin-tunable settings for the Admin AI (live, no restart),
reusing the ai_prompts pattern. Plan: `PLAN_AI_CONTROL.md`.

## Acceptance criteria
- [x] `ai_control_settings` + `ai_activity_log` tables in `init_db` AND migration
      `0009_ai_control_activity` (fresh fork + existing DB both work).
- [x] `_ai_control_registry()` (14 knobs) + `get_ai_setting` (DB>env>default, TTL
      cache, typed coercion) + `set_ai_setting`/`reset_ai_setting` + cache bust.
- [x] Super-admin routes `GET/PUT/POST /admin/api/ai-control[/<key>[/reset]]`.
- [x] Repointed admin-chat reads to live settings: rate limit, retries/fallback/
      model, OpenAI timeout, history budget, respcache, sqlguard.
- [x] Defaults preserve current behavior; env vars are the fallback layer.

## Test requirements
- [x] `tests/test_ai_control.py` — precedence/coercion/unknown-key; super-admin
      GET/PUT vs client 403; **live rate-limit toggle 429s a flood with no
      restart**; tables exist via init_db.
- [x] Migration chain 0001→0009 applies clean (boot check).

## Verification
6/6 AI Control tests green vs embedded PG; alembic head 0009; 50/50 pylego unit
tests still pass (config gained 2 fields, no regression); byte-compile OK.

## Notes
`redact_enabled` + `activity_logging_enabled` appear in the registry now but are
consumed inside pylego.obs — task 031 passes the live values into obs so they take
effect there. Rate-limit STORE persists; the limiter wrapper is rebuilt per
request from live settings (so toggles apply without restart).
