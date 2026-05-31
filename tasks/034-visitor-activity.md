# Task 034 — Visitor AI activity tracking (Phase 6 / Epic A)

**Status:** done
**Branch:** task/034-visitor-activity
**Depends on:** 031 (ai_activity_log), roadmap PLAN_VISITOR_AI

## Goal
Track every visitor /api/chat turn in ai_activity_log, tagged surface='visitor',
viewable + filterable in the super-admin AI Activity tab. Toggleable + redacted +
fail-open, like the admin side.

## Acceptance criteria
- [x] `ai_activity_log.surface` column (init_db + migration 0010; default 'admin').
- [x] obs record + _ai_activity_persist carry `surface`.
- [x] Visitor generate() accumulates per-turn metrics (model/provider/rounds/
      tools/tokens/cost/status/final/question) and logs ONE row in a `finally`
      (guarded, redacted via pylego.redact, gated by activity_logging_enabled).
- [x] /admin/api/ai-activity ?surface=admin|visitor filter; AI Activity tab gains
      a Surface dropdown + column.

## Test requirements
- [x] surface column exists; a visitor turn writes a surface='visitor' row;
      API surface filter; admin + visitor logged distinctly.

## Verification
7/7 tests vs embedded PG; alembic head 0010; visitor /api/chat still 200 SSE
(instrumentation is tracking-only, fail-open, never touches the reply).

## Notes
Reuses the obs redaction + _ai_activity_persist sink. Cost estimated via
_admin_chat_estimate_cost_usd. Default activity_logging_enabled=on; turn off in
AI Control to stop recording either surface.
