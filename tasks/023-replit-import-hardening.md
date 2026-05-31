# Task 023 — Harden the monolith for a clean Replit re-import

**Status:** in_progress
**Branch:** task/023-replit-import-hardening
**Depends on:** —
**Can run in parallel with:** — (single task; fixes are interdependent via the new main.py)

## Goal

Pre-harden the local repo so the *next* git → Replit import boots cleanly under
gunicorn with no manual intervention. Port/preempt the six issues the Replit
Agent hit (and fixed only in its cloud copy). Full rationale + per-issue analysis
in the approved plan: `~/.claude/plans/serialized-floating-boot.md`.

## Research block (verified in plan mode)

- No `main.py` at root. Bootstrap (5 steps) lives in `app.py:38995` `__main__`
  block → never runs under gunicorn.
- `app.py:553` OpenAI client constructs with empty key → SDK crash on import.
- 6 raw `X-Forwarded-For` reads: app.py 20401, 27379, 27491, 27654, 30879, 31059;
  `ip_address VARCHAR(45)` cols at 1317 & 1689; good truncation pattern to mirror
  at 34298–34304.
- `dashboard.html:4439` `window.location.reload()` in CSRF wrapper.
- Migrations already correct (`0005_admin_chat_rag.py:59` creates extension first,
  guards all indexes). pgvector decision: **fail loudly + document** (no migration
  change).
- `.replit`: workflow `python app.py` (bootstraps), deploy `gunicorn app:app`
  (does NOT bootstrap).

## Acceptance criteria

- [ ] `main.py` exists: imports `app`, runs the 5 bootstrap steps idempotently at
      import, exposes `app` for `gunicorn main:app`, `python main.py` runs dev
      server. Honors `SKIP_ALEMBIC` + new `SKIP_DB_BOOTSTRAP`.
- [ ] App imports with no AI key set (no construction crash).
- [ ] All 6 XFF sites take first hop, capped ≤45 chars.
- [ ] CSRF wrapper shows a banner instead of `window.location.reload()`.
- [ ] pgvector-missing migration failure re-raised as one clear actionable message;
      other failures unchanged. Documented in `claudecode.md` (+ KEYS.md one-liner).
- [ ] `.replit` deploy + workflow both route through `main`.

## Test requirements

- `tests/test_replit_boot_hardening.py` (embedded Postgres, no mocks):
  empty-AI-key boot; bootstrap-on-import (historical table + `alembic_version`
  exist); XFF chain truncation regression.
- Byte-compile + pyflakes clean on `main.py` + `app.py`.
- `_gate_runner.py` still 377/377.

## Commits

(filled as work progresses)

## Drift reason

Plan asserted "migrations UNCHANGED — already correct." Running them on a fresh
embedded Postgres falsified that: the two parallel `0005_*` migrations both
`CREATE TABLE rag_chunks`/`rag_documents` with conflicting schemas (one with a
`tenant_id` column, one without), so `0005_admin_chat_rag`'s
`CREATE INDEX ... (tenant_id)` failed with "column tenant_id does not exist" on a
clean DB — the actual root cause Replit misdiagnosed as pgvector. Fixed by making
`0005_rag_knowledge_base` the sole owner of the shared tables (its schema is the
one `rag.py` uses: `tenant_id`+`storage_key`+`error_text`) and dropping the
conflicting redefinition from `0005_admin_chat_rag` (whose own tables
`rag_chat_turns`/`admin_chat_memories` — unused anywhere in the monolith — are
retained). Verified: migrations apply to head in either branch order; RAG schema
intact.

## Notes

pgvector strategy resolved with user: fail loudly + document (keep RAG/cache
features intact). mypy N/A — codebase untyped.
