# PLAN — Phase 5: AI Control & Activity

Make the Phase-4 Admin-AI knobs **panel-controlled + persisted**, and the
observability **visible in the panel**, reusing the proven `ai_prompts` DB-backed
pattern. New tables are created in `init_db` (so a fresh client fork works) AND in
Alembic migration `0009`. Full design: `~/.claude/plans/serialized-floating-boot.md`.

Decisions: activity log stores **metadata + content** (redacted, super-admin-only);
**two separate tabs** (AI Control, AI Activity). Settings precedence **DB > env >
default** so existing env setups keep working. Defaults preserve current behavior.

## Tasks
- **030 — AI Control settings backend** (done): `ai_control_settings` +
  `ai_activity_log` tables (init_db + migration 0009); knob registry + TTL-cached
  `get_ai_setting` (DB>env>default) + set/reset; super-admin routes
  `/admin/api/ai-control`; repoint admin-chat reads (rate limit, retries/fallback,
  timeout, history budget, respcache, sqlguard) to live settings.
- **031 — AI Activity persistence**: obs DB sink → `ai_activity_log` (redacted);
  `/admin/api/ai-activity`; row-cap prune.
- **032 — History summarization**: summarize dropped turns instead of dropping
  (cheap model, default off, fail-open).
- **033 — Admin tabs**: super-admin-only **AI Control** + **AI Activity** tabs.

Not automatic self-improvement — activity data enables manual review + evals.
