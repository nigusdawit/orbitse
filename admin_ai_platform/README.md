# Admin/AI Platform

A standalone, **embeddable** AI-concierge platform — the admin/AI half of the
original site template carved into its own Flask package. Point it at a Postgres
database and an OpenAI key and you get a hosted concierge product you can drop
onto **any** website (a JS snippet) or into **WordPress** (a plugin), without the
client ever touching the code.

The public marketing-website rendering is intentionally **not** here — this is
the brain + the admin, designed to attach to an existing site.

---

## What's inside

| Area | What it does |
| --- | --- |
| **Visitor chat** | Streaming concierge with a compact site index + function-calling lookup tools, `generatePage` live-rendered into a sandboxed iframe, gallery navigation, conversational forms. |
| **Voice** | Sentence-streamed TTS (OpenAI / ElevenLabs) + STT (Web Speech / Whisper) + UTM intros. |
| **Admin AI** | State-aware assistant: read-only SQL + content edits gated behind an owner-approval flow. |
| **Cost** | Per-call ledgers, monthly caps (alert/throttle/block), editable prices, weekly digest. |
| **Skills / MCP** | Builtin lookup tools + admin-defined SQL & HTTP skills + MCP connectors, all callable mid-chat. |
| **RAG / KB** | pgvector knowledge base (degrades cleanly if pgvector is absent). |
| **Automations** | IFTTT engine (triggers/actions) + public webhook. |
| **Scraper** | SSRF-guarded fetch/extract + recurring schedules. |
| **Messaging** | Resend email + Twilio SMS, subscribers/templates/campaigns + webhooks + unsubscribe. |
| **Reviews** | Post-purchase asks, tracked `/r/<token>` short links, aggregate snapshots. |
| **Presentations** | AI-launchable decks. |
| **Commerce** | Services + a booking availability engine (capacity-aware) + products/orders (Stripe-ready). |
| **Tenancy** | Plans/features, embed keys + origin allowlists, snapshot/clone, secrets view. |
| **VELO** | Token-authed `/api/velo/command` agency control channel. |
| **Distribution** | `embed/loader.js` snippet (Shadow-DOM) + `wordpress-plugin/` (settings + auto-embed + SSO admin iframe). |

---

## Quick start

```bash
# 1. Postgres + an OpenAI key (pgvector optional — enables the KB)
export DATABASE_URL="postgresql://user:pass@host:5432/db"
export OPENAI_API_KEY="sk-..."            # or AI_INTEGRATIONS_OPENAI_API_KEY (proxy)
export FLASK_SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="choose-something"

# 2. Run (schema self-bootstraps on first boot)
python -m admin_ai_platform
#    prod: gunicorn "admin_ai_platform:create_app()" --bind 0.0.0.0:5000 --workers 4

# 3. Visit
#    Demo widget:  http://localhost:5000/demo
#    Admin:        http://localhost:5000/admin   (log in with ADMIN_PASSWORD)
#    Health:       http://localhost:5000/healthz
```

All optional integrations **fail open**: a missing key disables that feature, the
app still boots.

---

## Deployment & admin modes (pick per client)

Two env flags select all four shapes from one codebase:

| `DEPLOY_MODE` | `ADMIN_MODE` | Use it when… |
| --- | --- | --- |
| `self_host` | `self_serve` | One client runs their own copy; they log into `/admin`. Same-origin widget needs no embed key. |
| `self_host` | `agency_only` | Client's own copy, but only you (the agency) administer it. |
| `central` | `self_serve` | You host one multi-tenant SaaS; each client gets an embed key + logs into their tenant admin. |
| `central` | `agency_only` | You host it and administer every tenant; clients only get the embedded widget. |

> **Data isolation:** the shipping model is **one database per tenant** (each
> client install has its own Postgres). `tenants`/`tenant_features`/embed-keys
> manage feature flags + keys, not per-row isolation. Single-DB multi-tenancy
> (adding `tenant_id` scoping to every content query) is a follow-on.

---

## Key env vars

`DATABASE_URL`, `FLASK_SECRET_KEY`, `ADMIN_PASSWORD` · `OPENAI_API_KEY` /
`AI_INTEGRATIONS_OPENAI_*`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY` ·
`DEPLOY_MODE`, `ADMIN_MODE` · embed/SSO: `EMBED_ALLOWED_ORIGINS`,
`SSO_SIGNING_SECRET`, `CSP_FRAME_ANCESTORS`, `SESSION_COOKIE_SAMESITE`,
`SESSION_COOKIE_SECURE` · integrations: `RESEND_*`, `TWILIO_*`, `STRIPE_*`,
`BRAVE_SEARCH_API_KEY`, `GOOGLE_PLACES_API_KEY`/`YELP_API_KEY`/`TRIPADVISOR_API_KEY`,
`SCRAPER_*` · `VELO_SHARED_SECRET` · `TTS_MAX_CHARS`, `VOICE_DAILY_CHAR_CAP`,
`UPLOADS_DIR`, `DB_POOL_MIN/MAX`, `SENTRY_DSN`.

See `INTEGRATION_GUIDE.md` (embed snippet + WordPress) and `PROMPT_GUIDE.md`
(the AI command model).

---

## Tests

```bash
uv run python -m pytest admin_ai_platform/tests/   # unit (DB tests skip w/o DATABASE_URL)
uv run --with ruff ruff check admin_ai_platform/   # lint
```

A DB-backed integration gate (`_gate_runner.py`) stands up an ephemeral Postgres
(via `pgserver`) and exercises every subsystem end-to-end — 159 checks at last run.
