# Task 021 — M21: verification (browser + live-key E2E + CI)

## Goal
Close every "unverified in sandbox" gap with real-environment proof.

## Acceptance criteria
- [x] **CI**: `.github/workflows/ci.yml` runs ruff + the embedded-Postgres gate +
      pytest + dashboard/loader/widget JS syntax checks + `php -l` on the plugin,
      on every push/PR. The gate self-provisions Postgres (pgserver+pgvector), so
      no service container is needed.
- [x] **Verification report + runbook** (`admin_ai_platform/VERIFICATION.md`):
      records the automated PASS (gate 377/377, unit 71p/2s, lint clean) and the
      exact commands for the environment-dependent passes, with `_preview_app.py`
      as the browser launcher.
- [~] Browser E2E / live-key E2E / WordPress install / Docker boot: **scripted +
      checklisted, not runnable in the dev sandbox** (no browser, keys, PHP, or
      Docker here). CI provides Node + PHP for the syntax/lint portions; the live
      passes are the operator's to run per VERIFICATION.md.
- [x] Per-blueprint unit backfill: every Phase-2 milestone shipped its own unit
      file (scheduler, stripe, events, lookups, integrations, analytics, onboarding,
      security, deploy, fleet) alongside the gate's per-route integration coverage.

## Test requirements
- This task IS the verification. Produce a short PASS/known-issues report; update
  PLAN_PHASE2 → COMPLETE with the residual list (if any).

## Dependencies: 011–020, 022   ## Status: done   ## Branch: task/021-real-env-verification

## Notes
Merged to main (--no-ff). Delivered: GitHub Actions CI (ruff + gate + pytest +
JS syntax + php -l) and `admin_ai_platform/VERIFICATION.md` (PASS report +
runbook). Final automated state: **gate 377/377, unit 71p/2s, ruff clean.**
Re-applied the commerce TIME-serialization fix (`_jsonable_row` in add_rule/
add_override) that the spawned side-task added checks for but whose code change
was lost in a branch shuffle. Environment-dependent passes (browser, live keys,
WP, Docker) are honestly out of sandbox reach and left as the operator runbook.
PLAN_PHASE2 marked COMPLETE.
