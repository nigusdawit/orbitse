# Task 032 — History summarization (Phase 5)

**Status:** done
**Branch:** task/032-history-summarize
**Depends on:** 030

## Goal
When the admin-chat history is trimmed to the token budget, optionally summarize
the dropped oldest turns into a compact note instead of forgetting them. Plan:
`PLAN_AI_CONTROL.md`.

## Acceptance criteria
- [x] `pylego.history.trim_to_budget(..., summarize_fn=None)`: drops to fit, then
      (if summarize_fn given + something dropped + the note fits) keeps ONE
      system summary note in place of the dropped block; fail-open to plain drop;
      summarize_fn=None is byte-identical to before.
- [x] `_admin_history_summarize` (cheap gpt-4o-mini, fail-open) wired into the
      trim call, gated by the live `history_summarize_enabled` setting (default off).

## Test requirements
- [x] Unit: summarize_fn receives the dropped block + its note appears; failure
      falls back to plain drop; None == plain drop; system prompt + current turn
      always preserved.

## Verification
15/15 context tests; pyflakes clean; byte-compile OK. Default off → identity.

## Notes
Summarization adds one cheap LLM call only when it fires (budget>0 AND overflow
AND the toggle on). Tunable from the AI Control tab (task 033).
