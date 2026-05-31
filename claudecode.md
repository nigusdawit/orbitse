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

## Phase 6 visitor-AI program — COMPLETE (tasks 034–050)

The whole Phase 6 roadmap landed on `main` (NOT yet pushed to origin — pending
a manual push). Every feature is **gated default-off, master-kill-switch-aware
(AI_ENHANCEMENTS_ENABLED), tracked, and super-admin-managed** via the AI Control
registry + DB-backed `ai_control_settings`. New tables live in BOTH `init_db()`
and Alembic (migrations **0012–0018**) so a fresh client fork is consistent
either way; the chain applies clean 0001→0018.

Shipped: model routing (040) · prompt caching (041) · visitor CRM profiles (042)
· newsletter + `/preferences` portal (043) · offers engine (044) ·
capture_lead/request_callback/notify_team (045) · visitor persona router (046) ·
book_meeting (047) · callback AI handoff summary (048) · live-call scaffolding
(049) · super-admin admin tabs for all of it (050: Offers, Personas, Leads&CRM).

131 unit/integration tests (embedded Postgres via pgserver) — all green.

### Operator runbook — credential-dependent legs (built as scaffolding)

These features run store-only / decline until their creds are supplied:

- **Meetings (047) live calendar push:** connect a Calendar MCP server in the
  Connectors tab whose create-event tool accepts
  `{summary,start,duration_minutes,attendee_email,description}`, then set
  AI Control → Meetings → `meeting_calendar_mcp_server` (+ `meeting_calendar_tool`).
  Without it, `book_meeting` records requests as `status='requested'`.
- **Live phone call (049):** point your Twilio **Voice** number's webhook at
  `POST /webhooks/twilio/voice` (status callback `/webhooks/twilio/voice-status`),
  set `VOICE_WSS_URL` to a public wss media-stream bridge endpoint, enable
  `live_call_enabled`. **`TWILIO_AUTH_TOKEN` is MANDATORY** — the voice webhooks
  FAIL CLOSED (reject) without it (the SMS webhooks fail open for dev; voice does
  not, by design, because it has side effects + routes real calls). Without a wss
  endpoint the caller hears a spoken fallback.
- **Team notifications (045):** set AI Control → Growth Tools → `team_notify_email`
  / `team_notify_sms` (requires Resend / Twilio configured). Outbound is capped
  per tenant per minute via `TEAM_NOTIFY_MAX_PER_MIN` (default 10).

### Security notes (from per-task security-review)

- `/preferences` portal + voice webhooks FAIL CLOSED when the relevant secret
  (`FLASK_SECRET_KEY` / `TWILIO_AUTH_TOKEN`) is unset — a misconfigured host
  can't be used to forge capability tokens or spoof calls.
- `notify_team` can ONLY message the operator-configured destination (the agent
  supplies subject/message, never a recipient).
- Visitor-profile summaries/tags are PII-redacted before storage.

### Still outstanding (intentionally not done this session)

- **Push `main` to origin** — all Phase 6 work is local-only.
- **7 missing Python ports** in `~/lego/packages-py/` (typed_config,
  langfuse_client, eval_harness, llm_router, rate_limit, pii_redact,
  structured_llm) — independent of this app.
