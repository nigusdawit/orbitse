# Task 026 — pylego foundation + Observability + Evals

**Status:** done
**Branch:** task/026-pylego-observability-evals
**Depends on:** —

## Goal

Stand up the `pylego/` package and the first track of Admin AI improvements:
observability (tracing) + an eval harness, wired strictly additively. Plan:
`PLAN_ADMIN_AI.md`.

## Acceptance criteria

- [x] `pylego/` package: `config.py` (typed env config + per-feature enabled flags),
      `obs.py` (pass-through tracer), `evals/` (runner + seed suite), README.
- [x] `observe_admin_turn` wired into BOTH admin chat call sites
      (`admin_agent_chat_stream`, `_admin_chat_run_loop`) as a pass-through.
- [x] Default = structured local logging; auto-Langfuse when `LANGFUSE_*` set.
- [x] Non-disruption proven: obs yields events byte-identical, never swallows the
      loop's own errors, swallows its own backend errors.

## Test requirements

- [x] `tests/test_pylego_obs.py` — pass-through (enabled+disabled), malformed
      events, underlying-error re-raise, early-close, backend-failure swallow.
- [x] `tests/test_pylego_evals.py` — assertion types, llm_judge skip, per-case
      isolation, JUnit, seed suite.
- [x] Boot harness: app boots with wiring; `/admin/api/chat/stream` returns 200
      SSE through the obs wrapper (verified vs embedded Postgres).

## Verification

12/12 pylego unit tests green; byte-compile + obs boot harness PASS (stream 200,
events flow through obs intact, RAG/persona degrade gracefully on missing key).

## Drift reason

(none)

## Notes

`obs._emit` logs `error_text` (truncated 500c) from exceptions — PII/secret
redaction of that field is deferred to task 029 (`redact.py`). Langfuse + ragas
are optional, lazy-imported; absent → local logging / skipped.
