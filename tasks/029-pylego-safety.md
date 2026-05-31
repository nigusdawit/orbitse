# Task 029 — pylego Safety (Admin AI)

**Status:** done
**Branch:** task/029-pylego-safety
**Depends on:** 028

## Goal

Safety hardening for the Admin AI: SQL guard, PII/secret redaction, validated
tool args, hardened approval queue — strictly additive, never weakening the
monolith's existing protections. Plan: `PLAN_ADMIN_AI.md`.

## Acceptance criteria

- [x] `pylego/redact.py`: PII/secret redactor (tokens, Bearer, key=val, email,
      long digit runs); total/never-raises. Wired into `obs._emit` to sanitize
      log/trace `error_text` (default ON — log-only, can't change behavior).
- [x] `pylego/sqlguard.py`: independent read-only SELECT/WITH validator
      (comment-stripped, no multi-statement, forbidden-keyword scan); wired as an
      OPTIONAL extra gate in `_admin_tool_run_sql` AFTER the existing
      `_admin_safe_sql` (default off; can only reject more, never permit more).
- [x] `pylego/structured.py`: `parse_tool_args` + `run_with_repair` (tested;
      opt-in, unwired — the monolith already tolerates malformed args).
- [x] `pylego/action_queue.py`: `validate_transition` (terminal states final →
      idempotent approve/reject) + `idempotency_key` (tested module).
- [x] Defaults: sqlguard/structured OFF; redact ON (log-only).

## Test requirements

- [x] `tests/test_pylego_safety.py` — redact masking/passthrough/mapping +
      obs→redact wiring (secret never reaches the log); sqlguard allow/reject/
      multi-stmt/comment-hiding/empty; structured parse + repair loop;
      action_queue transition machine + idempotency key.
- [x] Embedded-PG boot: default stream unchanged; sqlguard ON → SELECT works,
      write blocked.

## Verification

49/49 pylego unit tests (15 safety); pyflakes clean; `_safe_boot.py` PASS;
**security-review: no findings ≥8 — strictly additive confirmed** (sqlguard
add-only, redact log-only + fail-open, no ReDoS, defaults sound).

## Drift reason

The monolith's safety was already strong (existing `_admin_safe_sql`,
`_redact_*`, approval flow), so the NET-NEW wired win is redacting the
observability `error_text` (the one place 026 added that emits exception text).
sqlguard is wired as an opt-in stricter layer; `structured` + `action_queue`
ship as tested reusable modules rather than retrofitting the live tool/approval
paths — force-wiring duplicate logic there would risk disruption for marginal
gain, which the "only enhance, never disturb" mandate forbids.

## Notes

Completes the Phase-4 Admin AI hardening initiative (026–029). All pylego
modules are inert-or-log-only at default config; the admin agent behaves exactly
as before unless an operator opts a feature in via env.
