# Task 031 — AI Activity persistence (Phase 5)

**Status:** done
**Branch:** task/031-ai-activity
**Depends on:** 030

## Goal
Persist every admin-AI turn to `ai_activity_log` (metadata + redacted Q/A) via an
obs DB sink, and expose it to the super admin. Plan: `PLAN_AI_CONTROL.md`.

## Acceptance criteria
- [x] `pylego.obs.observe_admin_turn` accepts injected `persist_fn` + `redact_enabled`;
      builds a full per-turn record (model/provider/rounds/tools/tokens/cost/
      duration/status + redacted user_message/final_answer/error_text); fail-open.
- [x] Fixed the tally bug: usage is nested under `evt["usage"]` (tokens/cost were 0).
- [x] `_ai_activity_persist` writes a row when `activity_logging_enabled` (live);
      opportunistic prune to ~5000 rows; both chat call sites wired.
- [x] `GET /admin/api/ai-activity` (super-admin) — recent rows + totals.
- [x] redact now driven by the live `redact_enabled` setting (closes the 030 note).

## Test requirements
- [x] obs unit: persist_fn receives the correct record (nested-usage fix), fail-open,
      redact on/off behavior.
- [x] integration (embedded PG): a turn writes one row; super-admin lists it;
      client → 403; disabling logging live stops new rows.

## Verification
10/10 obs unit tests; 9/9 activity+control integration tests vs embedded PG.

## Notes
Even a turn that errors on a missing LLM key is logged (status reflects it) — every
turn is recorded. Content is redacted before storage + super-admin-only read.
