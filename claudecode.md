# claudecode.md — running context log

A pick-up-cold context file for this repo. Holds conventions, gotchas, env-var
quirks, and decisions. NOT the plan or task list (those live in
`~/.claude/plans/` and `tasks/`).

## What this project is

The shipping product is the **Flask monolith** `app.py` (~39k lines): public site,
AI concierge (text + voice), admin dashboard, commerce, fleet sync, embed widget,
WordPress SSO. `admin_ai_platform/` is an extracted reference package — NOT what
ships. Postgres + Alembic (two-track: `init_db()` owns historical tables; Alembic
owns everything added after April 2026).

## Entry point & run pattern (since 2026-05-30)

**`main.py` is the canonical entry point** for every launch path:
- `gunicorn main:app` (deploy / Replit)
- `python main.py` (dev)

`main.py` imports `app`, then runs the schema bootstrap **once at import time**
(`init_db` → Alembic → skill syncs → chat-session backfill), so the DB is
bootstrapped regardless of how the process is launched. `.replit`'s `run`,
"Start application" workflow, and `[deployment]` all point at `main`.

Do NOT rely on `python app.py`'s `__main__` block for bootstrap under a WSGI
server — gunicorn never runs it. That was the original "tables don't exist on a
fresh deploy" bug.

Boot escape hatches: `SKIP_DB_BOOTSTRAP=1` (skip all bootstrap),
`SKIP_ALEMBIC=1` (skip migrations only).

## pgvector is a hard dependency

Migrations `0003`, `0005_admin_chat_rag`, `0005_rag_knowledge_base` require the
PostgreSQL **`vector` (pgvector)** extension (RAG + semantic-cache features).
`CREATE EXTENSION IF NOT EXISTS vector` still errors if the extension isn't
installed on the *server*, which aborts the migration.

- **On Replit:** enable pgvector on the database (Database pane / the Agent's
  "install pgvector" step) before/at first boot.
- If pgvector is genuinely unavailable, `main.py` now fails with a clear,
  actionable message (instead of a cryptic mid-migration trace). To boot without
  the RAG/semantic-cache features, set `SKIP_ALEMBIC=1`.

## Gotchas discovered

- **OpenAI client constructs even with no key.** `app.py` passes a sentinel
  (`sk-not-configured`) when `AI_INTEGRATIONS_OPENAI_API_KEY` is empty, because
  the newer `openai` SDK raises at construction on an empty key — which used to
  crash the import on a freshly-provisioned host. Real calls 401 until a key is
  set; the per-call error handling surfaces that as "AI not configured."
- **`X-Forwarded-For` is a chain behind Replit's proxy** (`client, proxy1, ...`).
  The `ip_address` columns are `VARCHAR(45)`. All read sites take the first hop
  and cap at 45 chars; storing the raw header overflowed the column.
- **Admin dashboard inside Replit's iframe:** never call
  `window.location.reload()` programmatically — it trips Replit's webview overlay
  and looks like a crash. The CSRF wrapper shows a Refresh banner (user gesture)
  instead.

## Local divergence note

The Replit *cloud* copy and this git repo have diverged before (Replit Agent
patched boot issues only in its cloud copy). The fixes above port those into git
so a fresh import is clean. Keep git as the source of truth; have Replit pull
rather than hand-editing in the cloud.
