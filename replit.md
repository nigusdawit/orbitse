# Database-Driven Website Template

> **AI agents:** read [`AGENT_KNOWLEDGE_BASE.md`](./AGENT_KNOWLEDGE_BASE.md) first — it is the canonical agent-oriented map of this project (architecture, routes, tables, env vars, conventions).
>
> This `replit.md` is the **trimmed** project README. The full long-form feature changelog (every feature in exhaustive detail) was archived to [`replit_20260531.md`](./replit_20260531.md) on 2026-05-31. Consult that archive when you need the deep history of a specific feature.

## Overview

A database-driven website template built as a reusable, industry-agnostic HTML/CSS/JS application. All content (gallery, experiences, pricing, site settings, chatbot, blog, events, services, forms, etc.) is managed through a PostgreSQL database and a password-protected admin dashboard — no code editing needed to change content. Suitable for any business type: hospitality, real estate, restaurants, portfolios, agencies, and more.

High-level feature areas (see the archive for full detail on each):

- **Public landing page** — snap-scroll sections (hero, highlights, experiences, pricing, testimonials, team, FAQ, blog, business info/contact), an immersive fullscreen gallery, and a 3D "Sphere View".
- **AI concierge chatbot** — streaming chat with site-control commands (navigate, showSlide, generatePage), a compact index + on-demand function-calling "lookup" tools, split-screen / side-panel / auto-canvas rendering, markdown + DOMPurify sanitization.
- **Proactive AI voice agent** — UTM-targeted welcome intros, visitor voice input (Web Speech or Whisper), and AI voice replies (OpenAI TTS or ElevenLabs) with sentence-by-sentence streaming TTS.
- **Commerce & bookings** — storefront/cart + Stripe checkout, event ticketing/donations, and a full Service Bookings system (rsvp/deposit/full/contract pricing, add-ons, calendar availability).
- **Content systems** — blog, dynamic multi-step form builder (with partial/abandon capture), custom section builder (11 templates), page layout manager, theme/color editor, SEO management, visitor analytics.
- **AI operations** — system-prompt editor, admin chat with Knowledge Base RAG (pgvector), web scraper with schedules, cost-transparency dashboard + weekly digest, review collector.
- **Faster Visitor AI Chat** (task/079, speeds up `POST /api/chat`) — Phase 1 (all clients, behavior-preserving): the system prompt is reordered into a byte-stable cacheable prefix + dynamic suffix, provider prompt caching is enabled (Anthropic tools-block + system-prefix `cache_control` with fail-open retry; OpenAI automatic), and the `generatePage` design block is trimmed (command blocks fenced verbatim, gated by an equivalence battery) so the big fixed context is re-read from cache instead of re-prefilled. Phase 2 (optional, per-client, **default-off / inert / fail-open**): a hybrid specialist router (keyword → embedding → tiny AI classifier on ambiguity) picks a specialist sub-prompt + minimal tool subset per turn, built by extending `_visitor_apply_persona`; it always keeps custom/MCP skills, inserts the specialist sub-prompt as a separate system message (preserving the Phase-1 cache prefix), and any error falls back to the full default prompt + all tools. It activates only when the AI master-kill **and** the `visitor_specialist_router_enabled` operator knob **and** the per-client `visitor_specialist_router` flag are all on; otherwise the exact single-agent flow runs. No migration (the flag lazy-seeds, the 5 specialist prompts are rows, the knobs are config). See `docs/faster-visitor-chat/blueprint.md`.
- **Admin dashboard** at `/admin` (password-protected) for editing all content; changes are instantly live on the public site.
- **Phase 6 — Visitor AI growth program** (merged 2026-05): visitor profiles/personas, offers, leads & callback requests, meetings, voice calls, AI control settings + activity log, RAG audience scoping, and super-admin-gated admin tabs.

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.
The entire template is industry-agnostic — naming, comments, and instructions avoid hotel/villa-specific language.

## Credentials Status (April 2026)

Secrets present in this Repl but **still holding placeholder values** — the matching features will fail or no-op until real values are pasted in:

- `RESEND_WEBHOOK_SECRET` — fail-open: webhook accepts events without signature check; status updates still post but anyone can spoof them
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — SMS campaigns + STOP-keyword opt-out + inbound-SMS webhook will return errors until real Twilio creds are set
- `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY` — reviews aggregator (Reviews → Insights tab) returns empty / error responses for the matching providers

Confirmed working with real values: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `BRAVE_SEARCH_API_KEY` (AI chat/voice/embeddings, Claude fallback, and AI web search), `ADMIN_PASSWORD`, `ADMIN_EMAIL`, `ADMIN_PHONE`, `FLASK_SECRET_KEY`, `ELEVENLABS_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `SENTRY_DSN`, plus the Replit-managed integrations (Stripe, database).

Note: the Replit OpenAI **proxy** (`AI_INTEGRATIONS_OPENAI_API_KEY`) is not set, so `openai_client` falls back to the direct `OPENAI_API_KEY` against `api.openai.com` (see the client init in `app.py`).

When debugging or adding features that touch the placeholder list, assume the upstream call will fail and surface a friendly error — don't gate new functionality on those features being live.

## System Architecture

### Backend (Python Flask)
- **Framework**: Flask (Python); **entry point**: `app.py`. Run via `gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app`.
- **Port**: 5000 (required for the Replit webview).
- **Serves**: static files from `public/`, admin templates from `templates/admin/`, REST API endpoints (public reads + admin CRUD), the chat API, and uploaded images from `uploads/`.
- **Module layout (de-monolithed)**: `app.py` (was ~46.8k lines) was split — shared infrastructure moved to `core.py` (~3.2k lines) and feature routes moved into **15 Flask blueprints under `admin/`** (`public_api`, `content`, `forms`, `offers`, `personas`, `commerce`, `sitebuilder`, `reporting`, `dashboards`, `crm`, `tenancy`, `ai_prompts`, `cost`, `products`, `ai_control`, plus the pre-existing `velo_bp`). Layering with no circular imports: `core.py → admin/*.py → app.py` (core.py's header reserves a lower `state.py` bottom layer that hasn't been split out yet — `core.py` is the bottom layer today). **No app factory** — the global `app` object is kept, so `main.py`/gunicorn/tests still bind to it. Blueprints import only from `core` (never `from app`); `app.py` re-exports every moved symbol so `app.X`, `from app import X`, and the test suite keep resolving. `app.py` is now a slim aggregator (imports, re-exports, blueprint registration, the global `before_request` hooks, VELO wiring, `__main__`) that still holds `init_db()` and the AI/business logic not yet carved out (~40.5k lines). `core.py` holds the Flask app + extensions, the DB helpers (`get_db`/`query_db`/`execute_db` + pool), the auth gates (`admin_required`/`_is_super_admin`/`_require_super_admin_role`), the feature-flag subsystem (`_FEATURE_REGISTRY`/`tenant_has_feature`), the prompt subsystem (`SYSTEM_PROMPT`/`get_prompt`), the AI-Control settings subsystem (`_ai_control_registry`/`get_ai_setting`), and the cost/billing infra. This was a pure code move — **no DB/schema change**, `current_tenant_id()` still resolves to `1`, and the route table is byte-identical (enforced by a route-snapshot test).

### Public Site (Static HTML/CSS/JS — no build step)
- **Location**: `public/`
  - `index.html` — page structure (landing + gallery + modal + chatbot + split-screen)
  - `styles.css` — all visual styles (fully commented)
  - `script.js` — all interactivity (API fetches, navigation, animations, chatbot, AI site control, theme loading, dynamic forms, section visibility)
  - `voice.js` — standalone voice-agent frontend
- **Fonts**: Google Fonts (Playfair Display + DM Sans, swappable via Theme Editor). **Icons**: Lucide (CDN).

### Admin Dashboard
- **URL**: `/admin` (redirects to `/admin/login` if unauthenticated); password via `ADMIN_PASSWORD` (default `"admin"`).
- **Location**: `templates/admin/dashboard.html` (the slim **shell**, ~1.7k lines), `templates/admin/login.html`.
- **Front-end layout (de-monolithed, task/076)**: `dashboard.html` was a 29,240-line monolith and is now a ~1,689-line **shell** + ~65 per-tab Jinja partials (`templates/admin/tabs/_*.html`, pulled in with `{% include %}`) + extracted static assets under `public/admin/` (served via `<link>`/`<script src>`). There is **no build step** (no Tailwind/bundler/framework) and the assets are **not** ES modules — all admin JS functions stay GLOBAL so the inline `onclick=` handlers keep working. Assets: `base.css` (global reset + `:root` theme vars + the reused `.btn`/`.card`/`.badge`/`.tab-*`/`.form-*` classes), `theme.css` (glass theme layer + `gx-*` kit), `tabs.css`, `csrf.js` (CSRF fetch wrapper + some feature JS), `app-main.js` (the bulk of admin JS), `services.js`, `presentations.js`. What stays in the shell: the sidebar nav with its `{% if is_super_admin()/has_feature() %}` gates, the inline `#admin-appearance-vars {{ appearance.* }}` block, and the global modals. Maintainer aids: `templates/admin/README.md` (tab→partial→JS→endpoint map + "how to add a tab" recipe) and a live component gallery at `public/admin/styleguide.html`.
- **Tabs**: Page Layout, Site Settings, Gallery, Experiences, Pricing, Business Info, Testimonials, Team, FAQ, Blog, Saved Pages, Sphere View, SEO, Chatbot, Chat History, Forms, Theme, Analytics, plus the System group (Performance, Developer, Stripe, Secrets, Cost, and the super-admin-gated growth/CRM tabs). The full canonical tab list lives in `AGENT_KNOWLEDGE_BASE.md` §12.

### Database (PostgreSQL)
- **Connection**: `DATABASE_URL`.
- **~112 tables** covering content, commerce, chat, voice, analytics, RAG, cost ledgers, and the Phase 6 CRM/growth tables. Per-table column detail lives in `AGENT_KNOWLEDGE_BASE.md` and the archive.

## Schema Migrations (Alembic) — READ BEFORE TOUCHING THE SCHEMA

The project uses **two coexisting schema tracks**, both run on dev boot in this order after the pool initializes:

1. **`init_db()` in `app.py`** — the LEGACY fresh-install path. Idempotent (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` only). **This code is FROZEN — never add new tables/columns to it.**
2. **`_run_alembic_upgrade()` in `app.py`** — runs `alembic upgrade head` against the live `DATABASE_URL`.

⚠️ **All new tables and columns MUST go through an Alembic migration.** The legacy in-code schema setup silently skips appended tables on an existing DB, so a table added there will never be created on an already-provisioned database.

### Adding a column or table
```bash
uv run alembic revision -m "add foo column to bar"   # 1. create revision under migrations/versions/
# 2. edit it — op.add_column()/op.create_table()/op.execute(); downgrade() must be a precise inverse
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head   # 3. test
# 4. restart the dev workflow so _run_alembic_upgrade() picks it up
# 5. commit BOTH the revision file AND the code that depends on it
```

### Escape hatches & inspection
- `SKIP_ALEMBIC=1` — bypass the boot upgrade (emergency recovery only).
- `uv run alembic upgrade head --sql` — render pending SQL without applying.
- `uv run alembic current` / `uv run alembic history` — inspect the live revision and history.

### Known limitation
`init_db()` and `_run_alembic_upgrade()` are called only from the `__main__` block in `app.py`, so the dev workflow runs them but production gunicorn and the pytest fixture do not — both rely on the dev boot to keep the DB in sync.

### Files
`alembic.ini`, `migrations/env.py` (connects via the live `DATABASE_URL`; `target_metadata = None` — every revision is hand-written), `migrations/script.py.mako`, `migrations/versions/` (revisions; `0001_baseline` is intentionally empty).

## External Dependencies

### Required / common environment variables
- `DATABASE_URL` — PostgreSQL connection string (provisioned by Replit)
- `ADMIN_PASSWORD` — admin login password (default `"admin"`)
- `FLASK_SECRET_KEY` — session encryption key (also signs unsubscribe tokens)
- `AI_INTEGRATIONS_OPENAI_API_KEY` / `AI_INTEGRATIONS_OPENAI_BASE_URL` — set by Replit AI Integrations
- `OPENAI_API_KEY` — direct OpenAI key (required for `/audio/*` voice features the proxy doesn't support)
- `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` / `STRIPE_WEBHOOK_SECRET` — payments (Replit Stripe connection preferred; env vars are fallback)
- `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `RESEND_WEBHOOK_SECRET` — email + webhook verification
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` — SMS (env-only, no connector)
- `ELEVENLABS_API_KEY` — premium TTS (optional)
- `GOOGLE_PLACES_API_KEY` / `YELP_API_KEY` / `TRIPADVISOR_API_KEY` — reviews aggregator (optional)
- `SENTRY_DSN` / `SENTRY_ENV` — error tracking (optional)
- `ADMIN_EMAIL` / `ADMIN_PHONE` — default "test send" destinations
- `SUPER_ADMIN_KEY`, `SSO_SIGNING_SECRET`, `CLIENT_PASSWORD`, `VELO_*` — super-admin/SSO/VELO features

The full env-var inventory with required/optional labels lives in `.env.example`. The admin **Secrets** tab manages these without exposing values.

### Python packages
`flask`, `psycopg2-binary`, `openai`, `anthropic`, `stripe`, `gunicorn`, `sentry-sdk[flask]`, `pgvector`, `pypdf`, `python-docx`, `python-pptx`, `pytest` (and others — see `pyproject.toml`, the source of truth).

### CDN dependencies
Google Fonts (Playfair Display, DM Sans + dynamic), Lucide Icons, SortableJS (admin drag-and-drop), DOMPurify (HTML sanitization), Chart.js (admin charts), Three.js + CSS3DRenderer (Sphere View).

## Project File Structure

```
app.py                 — slim Flask aggregator (re-exports, blueprint registration,
                         global before_request hooks, init_db, VELO wiring, __main__)
core.py                — shared infra imported by the blueprints (app + extensions,
                         DB helpers, auth gates, feature flags, prompts, AI-Control, cost)
admin/                 — 15 Flask blueprints (the feature routes split out of app.py)
main.py                — gunicorn entry (from app import app)
public/                — public site (index.html, styles.css, script.js, voice.js)
public/admin/          — extracted admin CSS/JS assets + styleguide.html (no build step)
uploads/               — uploaded image files (runtime)
templates/admin/       — dashboard.html (shell), login.html, README.md, tabs/_*.html partials
templates/blog_post.html
voice_bridge/          — standalone voice-bridge package (Phase 6)
migrations/            — Alembic config + versions/
embed/widget/          — embeddable chat widget bundle
chat-ui-kit/           — standalone sellable chat UI package
tests/                 — pytest suite (see memory note on env sensitivity)
pyproject.toml / uv.lock / requirements.in
Dockerfile / docker-compose.yml
.env.example           — full env-var inventory
AGENT_KNOWLEDGE_BASE.md — canonical agent-facing map (read first)
replit.md              — this trimmed README
replit_20260531.md     — archived full feature changelog
.replit                — Replit run/deploy configuration
```

## How to Edit Content & Customize
Use the admin dashboard at `/admin` to manage all content, layout, theme, SEO, and chatbot behavior — no code changes required. For developer-level customization, see `GUIDE.md` and `AGENT_KNOWLEDGE_BASE.md`. The exhaustive per-feature history is in `replit_20260531.md`.
