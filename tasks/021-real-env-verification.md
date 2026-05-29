# Task 021 — M21: verification (browser + live-key E2E + CI)

## Goal
Close every "unverified in sandbox" gap with real-environment proof.

## Acceptance criteria
- [ ] Browser E2E (Preview/Playwright): demo widget — gallery navigate, live
      `generatePage` render, conversational form submit, spoken reply; `/admin`
      tabs render + key actions; a cross-origin embed test page (Shadow DOM + CORS
      + 403 on bad origin); console-error-free.
- [ ] WordPress: `php -l` the plugin, install into a local WP (wp-env/docker),
      configure, confirm widget injects + the SSO admin iframe loads + a
      tampered/expired token is rejected.
- [ ] Live-key E2E smoke (scripted, opt-in via env): a real `/api/chat` round
      (OpenAI), voice TTS+STT, RAG ingest+retrieve, a Stripe test-mode purchase
      end-to-end (checkout→webhook→paid), a Resend email + Twilio SMS send.
- [ ] CI: run the embedded-Postgres gate + pytest + ruff + node --check + php -l
      on every push (GitHub Actions); document required service containers
      (postgres+pgvector).
- [ ] Per-blueprint unit-test backfill where thin.

## Test requirements
- This task IS the verification. Produce a short PASS/known-issues report; update
  PLAN_PHASE2 → COMPLETE with the residual list (if any).

## Dependencies: 011–020   ## Status: not_started   ## Branch: task/021-real-env-verification
