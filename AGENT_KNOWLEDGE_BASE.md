# AGENT KNOWLEDGE BASE

> **Audience:** AI coding agents (and new human contributors) who need to be productive in this repo
> without re-discovering it from scratch. Read this file first. Then dive into `replit.md` /
> `GUIDE.md` / `TEMPLATE_OVERVIEW.md` only when you need deeper detail on a specific feature.

---

## Table of Contents

1. [Project Purpose & Audience](#1-project-purpose--audience)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Tech Stack & Key Dependencies](#3-tech-stack--key-dependencies)
4. [Repository Layout](#4-repository-layout)
5. [Runtime — How to Run It](#5-runtime--how-to-run-it)
6. [Configuration — Environment Variables & Secrets](#6-configuration--environment-variables--secrets)
7. [Authentication, Sessions & Rate Limits](#7-authentication-sessions--rate-limits)
8. [Database Conventions](#8-database-conventions)
9. [Data Model Overview (by Domain)](#9-data-model-overview-by-domain)
10. [Backend Route Map](#10-backend-route-map)
11. [Frontend Overview (`public/`)](#11-frontend-overview-public)
12. [Admin Dashboard Overview](#12-admin-dashboard-overview)
13. [AI Subsystem (Visitor Chat & Admin Chat)](#13-ai-subsystem-visitor-chat--admin-chat)
14. [Voice Subsystem](#14-voice-subsystem)
15. [Commerce — Services, Bookings, Events, Store](#15-commerce--services-bookings-events-store)
16. [Forms Subsystem](#16-forms-subsystem)
17. [Reviews Subsystem](#17-reviews-subsystem)
18. [Scraping Subsystem (`scraper.py`)](#18-scraping-subsystem-scraperpy)
19. [Automations Subsystem (`automations.py`)](#19-automations-subsystem-automationspy)
20. [Notifications (`messaging.py`)](#20-notifications-messagingpy)
21. [Cost Transparency & Weekly Digest](#21-cost-transparency--weekly-digest)
22. [Analytics](#22-analytics)
23. [Security & Safety](#23-security--safety)
24. [Feature Flags & Their Behavior When Off](#24-feature-flags--their-behavior-when-off)
25. [External Integrations Summary](#25-external-integrations-summary)
26. [Conventions an Agent Must Follow When Editing](#26-conventions-an-agent-must-follow-when-editing)
27. [Placeholder Credentials & User-Visible Failure Modes](#27-placeholder-credentials--user-visible-failure-modes)
28. [Pointers to Deeper-Dive Docs](#28-pointers-to-deeper-dive-docs)
29. [Doc Drift](#29-doc-drift)

---

## 1. Project Purpose & Audience

A **database-driven, industry-agnostic website template** for a single small business (hospitality,
real estate, restaurant, portfolio, agency, etc.). All public-facing content (gallery, services,
pricing, blog, events, products, FAQs, testimonials, team, business info) is stored in PostgreSQL
and edited through a password-protected admin dashboard at `/admin`. There is no React build step —
the public site is plain HTML/CSS/JS.

Two audiences:

- **Public visitors** — see the immersive landing page at `/`, a fullscreen gallery view, the
  AI-powered chat concierge (text + voice), and bookable/buyable items.
- **Admins** — log in at `/admin/login`, manage all content, talk to an "Admin AI" that can mutate
  site state (with a pending-action approval flow for destructive operations), watch analytics, and
  configure cost caps, feature flags, and integrations.

The codebase is a **Flask monolith**: one ~30,500-line `app.py` plus four helper modules
(`automations.py`, `scraper.py`, `messaging.py`, `stripe_client.py`). All HTTP routes,
DB schema bootstrap, AI prompt construction, scheduler ticks, and webhook handlers live in
`app.py`.

---

## 2. High-Level Architecture

```
                      ┌──────────────────────────┐
   public visitor ──▶ │  Flask (app.py)          │ ◀── admin (password + session)
                      │  + Gunicorn (prod)       │
                      ├──────────────────────────┤
                      │  templates/admin/        │   <- Jinja for admin UI
                      │  public/ (static)        │   <- HTML/CSS/JS for public site
                      │  uploads/ (user files)   │
                      └─────┬──────────┬─────────┘
                            │          │
                            ▼          ▼
                  ┌──────────────┐  ┌────────────────────────────────┐
                  │ PostgreSQL   │  │ External providers              │
                  │ (raw psycopg2│  │ - OpenAI (via Replit AI proxy)  │
                  │  + JSONB)    │  │ - Anthropic (via Replit proxy)  │
                  │              │  │ - OpenAI direct (TTS / Whisper) │
                  │ ~70 tables   │  │ - ElevenLabs (premium TTS)      │
                  │ created in   │  │ - Resend (email)                │
                  │ init_db() on │  │ - Twilio (SMS / WhatsApp)       │
                  │ startup      │  │ - Stripe (payments)             │
                  └──────────────┘  │ - Sentry (errors)               │
                                    │ - ScrapingBee / Browserless     │
                                    │ - Google Places / Yelp /        │
                                    │   TripAdvisor (reviews)         │
                                    │ - Brave Search (chat tool)      │
                                    └────────────────────────────────┘
```

Key facts:

- **One process, one DB.** No worker queue, no Redis. Background work happens in a single
  scheduler thread inside `app.py` (cost caps, weekly digest, scrape schedules, automations runner,
  review request scheduler).
- **Schema is bootstrapped on every startup** by `init_db()` in `app.py` using
  `CREATE TABLE IF NOT EXISTS` — there is no separate migration step. `scripts/post-merge.sh` does
  not touch the DB.
- **Multi-tenant scaffolding exists** (`tenants`, `tenant_features`, `current_tenant_id()`) but
  every request currently resolves to **`tenant_id = 1`**. Always call `current_tenant_id()` —
  never hard-code `1`.
- **Replit AI Integrations** proxy the OpenAI / Anthropic LLM calls (`AI_INTEGRATIONS_OPENAI_*`).
  Audio endpoints (`/audio/speech`, `/audio/transcriptions`) are not proxied — they need a direct
  `OPENAI_API_KEY`.

---

## 3. Tech Stack & Key Dependencies

| Layer | Tech |
| --- | --- |
| Runtime | Python 3.11, Node.js 20 (only for tiny dev tooling), Nix-managed env |
| Web | Flask 3.x, Gunicorn (prod), Werkzeug ProxyFix |
| DB | PostgreSQL 16 + `psycopg2-binary` (raw SQL, no ORM) |
| AI | `openai`, `anthropic`, OpenAI Whisper, OpenAI TTS, ElevenLabs (HTTP) |
| Email / SMS | Resend (HTTP), Twilio (HTTP) |
| Payments | Stripe SDK (`stripe>=15`) |
| Errors | `sentry-sdk[flask]` |
| Scraping | `requests`, ScrapingBee or Browserless (rendered fetch) |
| Crypto | `cryptography` (Fernet — encrypts stored secrets in `agent_provider_settings`, etc.) |
| Files | `pillow`, `pymupdf`, `python-pptx` (for AI page / contract / deck handling) |
| Frontend | Plain HTML/CSS/JS, **DOMPurify** (sanitize AI HTML), **Lucide** icons, **Three.js + CSS3DRenderer** (Sphere View), **Chart.js** (admin dashboards), **Stripe.js** (storefront checkout), Web Speech API (free STT) |

Python deps are pinned in `pyproject.toml` (locked in `uv.lock`). Frontend libs are pulled from
CDNs in `public/index.html` and `templates/admin/dashboard.html` — there is **no bundler**.

**Forbidden:** do not edit `package.json` manually, do not change `vite.config.*`, do not modify
`drizzle.config.ts` (this project does not actually use Drizzle — it's plain SQL).

---

## 4. Repository Layout

| Path | Role |
| --- | --- |
| `app.py` | The monolith. All routes, schema bootstrap (`init_db`), AI prompt construction, scheduler ticks, webhook handlers, helpers. ~30,500 lines / ~1.4 MB. |
| `automations.py` | "If This Then That" workflow engine. Triggers, action runner, retention sweep, concurrency limits. Does not create tables — uses ones from `init_db`. |
| `scraper.py` | URL / objective scraper with SSRF guards, ScrapingBee / Browserless fallback, schedule runner. |
| `messaging.py` | Email (Resend) + SMS (Twilio) send helpers, opt-out handling, status webhooks. Always send through this — never call Resend / Twilio directly. |
| `stripe_client.py` | Thin wrapper around Stripe SDK that resolves keys from env / Replit Connectors. |
| `public/index.html` | Single-page public site shell (landing + gallery + modals + chat overlays). Server-side meta-tag injection at `<!-- SEO_META_INJECT -->` and `<!-- JSON_LD_INJECT -->`. |
| `public/script.js` | All public-site interactivity — fetches every `/api/*` endpoint, renders sections, runs gallery navigation, drives the chat / cart / booking modals (~8,500 lines). |
| `public/voice.js` | `VoiceAgent` module: STT dispatch (Web Speech vs Whisper), per-sentence streaming TTS queue, intro playback. |
| `public/styles.css` | All public-site CSS, organized in numbered sections; theme tokens come from CSS variables set by the Theme Editor. |
| `public/ai_concierge.png` | Default chat avatar. |
| `templates/admin/dashboard.html` | The entire admin UI (one big Jinja template + inline JS, all tabs). |
| `templates/admin/login.html` | Admin login form. |
| `chat-ui-kit/` | Standalone, embeddable chat widget (HTML / CSS / JS + a tiny Flask backend). Has its own `README.md`, `INTEGRATION_GUIDE.md`, `PROMPT_GUIDE.md`. **Not** part of the live app — it's a portable kit you can ship to other projects. |
| `attached_assets/` | User-uploaded reference assets (screenshots, design refs). Imported in frontend via `@assets/...` if needed. |
| `uploads/` | Runtime user uploads — images, signed contracts, voice TTS cache (`uploads/voice/<sha1>.mp3`), generated decks. Created on demand. |
| `scripts/post-merge.sh` | Runs after merges. `npm install` + `uv sync` only. **Does not** touch the DB. |
| `replit.md` | The big living changelog / architecture doc (~86 KB). Treat as feature-history detail; this file is the agent-friendly map. |
| `GUIDE.md` | "How to use the template" walkthrough for a non-developer site owner. |
| `TEMPLATE_OVERVIEW.md` | Short feature overview originally written when this was a hotel/villa template. |
| `.replit` | Replit config — modules, run command, deployment (autoscale gunicorn), workflows, integrations, post-merge hook. |
| `pyproject.toml` / `uv.lock` | Python dependency lockfile. |
| `package.json` / `package-lock.json` | Node deps for tiny dev tooling only — no app code is bundled. |
| `replit.nix` | Nix shim. |
| `.flask_secret` | Local fallback for `FLASK_SECRET_KEY` if the env var isn't set. |
| `data.db` | Empty stub from a long-dead SQLite path. Ignore — DB is Postgres. |
| `.local/tasks/*.md` | Per-feature task plans. Read these when working on a specific feature. |
| `.local/skills/`, `.local/mcp_skills/` | Replit-provided agent skills. |

---

## 5. Runtime — How to Run It

- **Workflow:** the `Start application` workflow runs `python app.py`, which serves on **port 5000**.
  The Run button (`npm run dev`) also dispatches to `python app.py`.
- **Production deploy** (autoscale, configured in `.replit`):
  `gunicorn --bind=0.0.0.0:5000 --reuse-port app:app`.
- **No build step** for the public site — files in `public/` are served directly by Flask.
- **Schema** is created/upgraded by `init_db()` on each startup (idempotent
  `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` patterns).
- **Workflow restart:** if you change any Python file, restart `Start application` to pick it up.
  Static frontend changes are picked up on browser reload.

---

## 6. Configuration — Environment Variables & Secrets

> All secrets are managed through the Replit Secrets panel. **Do not** echo or commit them.
> Always check whether a Replit integration / connector already provides a credential before
> asking the user for one.

### Core

| Var | Purpose | Required? |
| --- | --- | --- |
| `DATABASE_URL` | Postgres connection string | **Yes** |
| `FLASK_SECRET_KEY` | Session signing + Fernet key derivation for stored secrets | **Yes** (fallback to `.flask_secret` file) |
| `ADMIN_PASSWORD` | Admin login password (default `"admin"` if unset — never ship that) | **Yes** in real use |
| `ADMIN_EMAIL` | Where digest / cap / contact-form notifications go when no per-feature override is set | Recommended |
| `ADMIN_PHONE` | Admin SMS recipient | Optional |
| `PUBLIC_BASE_URL` | Used to build absolute links (Stripe success URLs, review short links, webhook URLs) | Recommended in deploy |

### Client mode / embed / WordPress SSO (May 2026)

| Var | Purpose | Required? |
| --- | --- | --- |
| `CLIENT_MODE` | Truthy (`1`/`true`/`yes`/`on`) flips operator-only features (currently `website_builder`) to **default off**, so a client install only sees the AI concierge. Unset on the operator's own install. | Per client install |
| `SSO_SIGNING_SECRET` | HMAC-SHA256 secret shared (byte-identical scheme) with the WordPress plugin for `/admin/sso` single-sign-on tokens. `/admin/sso` returns 503 until set. Never exposed to the browser. | Only if using WP SSO |

### AI providers

| Var | Gates |
| --- | --- |
| `AI_INTEGRATIONS_OPENAI_API_KEY` | Primary OpenAI access (LLM, via Replit AI Integrations proxy) |
| `AI_INTEGRATIONS_OPENAI_BASE_URL` | The proxy endpoint |
| `OPENAI_API_KEY` | **Direct** OpenAI key, used only for `/audio/speech` (TTS) and `/audio/transcriptions` (Whisper) — the proxy doesn't route those |
| `ANTHROPIC_API_KEY` | Claude as alternative LLM provider |
| `ELEVENLABS_API_KEY` | Premium TTS (gated by `voice` feature flag + `voice_settings.premium_enabled`) |
| `BRAVE_SEARCH_API_KEY` | Powers the `lookup_web_search` chat tool (gated by `web_search` feature flag) |

### Email / SMS

| Var | Gates |
| --- | --- |
| `RESEND_API_KEY` | All transactional email |
| `RESEND_FROM_EMAIL` | Sender address (must be verified in Resend) |
| `RESEND_WEBHOOK_SECRET` | Verifies inbound delivery / open / bounce events from Resend |
| `TWILIO_ACCOUNT_SID` | SMS / WhatsApp |
| `TWILIO_AUTH_TOKEN` | SMS auth + inbound webhook signature verification |
| `TWILIO_FROM_NUMBER` | Outbound sender number |

### Stripe

| Var | Gates |
| --- | --- |
| `STRIPE_SECRET_KEY` | Backend payments / Checkout session creation / webhook handling |
| `STRIPE_PUBLISHABLE_KEY` | Stripe.js Elements on the storefront |
| `STRIPE_WEBHOOK_SECRET` | Verifies incoming Stripe webhook signatures |
| `STRIPE_WEBHOOK_INSECURE_DEV` | Dev-only bypass for signature checks — never set in prod |

### Reviews aggregator

| Var | Gates |
| --- | --- |
| `GOOGLE_PLACES_API_KEY` | Google review snapshots |
| `YELP_API_KEY` | Yelp review snapshots |
| `TRIPADVISOR_API_KEY` | TripAdvisor snapshots |

### Scraping

| Var | Gates |
| --- | --- |
| `SCRAPER_RENDER_PROVIDER` | `scrapingbee` (default) or `browserless` |
| `SCRAPINGBEE_API_KEY` | JS-rendered fetch via ScrapingBee |
| `BROWSERLESS_TOKEN`, `BROWSERLESS_URL` | JS-rendered fetch via Browserless (self-hosted or cloud) |

### Automations limits (`automations.py`)

`AUTOMATIONS_MAX_CONCURRENT`, `AUTOMATIONS_MAX_PER_HOUR`, `AUTOMATIONS_MAX_RUN_SECONDS`,
`AUTOMATIONS_HTTP_TIMEOUT`, `AUTOMATIONS_DELAY_MAX`, `AUTOMATIONS_AI_TIMEOUT`,
`AUTOMATIONS_RETENTION_DAYS`, `AUTOMATIONS_RETENTION_KEEP_RECENT` — sane defaults are baked in;
override only if you need to.

### Sentry

`SENTRY_DSN`, `SENTRY_ENV` — error monitoring; init is no-op if `SENTRY_DSN` is unset.

### Replit-managed (do not set manually)

`REPLIT_DEPLOYMENT`, `REPLIT_CONNECTORS_HOSTNAME`, `REPL_IDENTITY`, `WEB_REPL_RENEWAL`,
`REPLIT_DOMAINS`. These come from the Replit runtime; the app reads them to detect prod
(turns on `SESSION_COOKIE_SECURE`) and to talk to the Replit Connectors broker.

See [§27](#27-placeholder-credentials--user-visible-failure-modes) for which secrets currently hold
**placeholder** values in this Repl.

---

## 7. Authentication, Sessions & Rate Limits

- **Public site:** no auth. Some endpoints (cart checkout, RSVP) accept anonymous POSTs.
- **Admin:** `/admin/login` posts the password; on success the Flask session gets
  `session["admin"] = True`. Every `/admin/...` route uses an `@admin_required` decorator that
  redirects unauthenticated browsers to the login page and returns 401 JSON to API clients.
- **Session cookie** is `Secure` only when `REPLIT_DEPLOYMENT` is set (production), so dev still
  works over plain HTTP.
- **Replit OAuth ("Log in with Replit")** is installed as an integration but the live admin gate
  is the password + session model. Replit Auth is available for future user-facing accounts.
- **`ProxyFix`** is wired so `request.remote_addr` honors `X-Forwarded-For` correctly behind
  Replit's proxy.
- **Rate limits** are in-process token-bucket counters keyed by IP (or session). Major call sites:
  - Visitor `/api/chat`: per-IP per-window cap; **drops to 5 req/window** when cost caps put the
    request in `throttle` mode (`g._cost_throttled`).
  - Voice `/api/voice/tts*` and `/api/voice/stt`: per-IP daily char and request caps
    (`TTS_DAILY_CHARS_PER_IP`, `STT_DAILY_REQUESTS_PER_IP`).
  - Form submission, scrape job creation, automations webhook ingress: per-IP per-window caps.
- **Webhook signatures** are verified server-side: Stripe (HMAC), Resend (HMAC, optional via
  `RESEND_WEBHOOK_SECRET`), Twilio (validates `X-Twilio-Signature` against the request URL +
  POST body using `TWILIO_AUTH_TOKEN`).

---

## 8. Database Conventions

- **Driver:** `psycopg2-binary`. There is **no ORM** — all SQL is raw and parameterized through
  `%s` placeholders.
- **Helpers** (defined in `app.py`):
  - `query_db(sql, params=(), fetchone=False)` — returns a list of `dict`s (or one dict if
    `fetchone=True`) using `RealDictCursor`.
  - `execute_db(sql, params=(), returning=False)` — write path; returns the row(s) when
    `returning=True`.
  - `get_db()` — opens a fresh connection per request via `g`.
- **Schema** is created in **`init_db()`** at startup. Same function applies idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations and seeds default rows
  (built-in `page_sections`, default chatbot settings, default theme, sample blog post, etc.).
- **Conventions:**
  - **`SERIAL` primary keys** named `id`. Never use UUIDs unless there's a strong reason.
  - **JSONB** for flexible nested data: `details`, `options`, `extra_data`, `social_links`,
    `business_hours`, `tool_calls_json`, `payload_json`, etc.
  - **Singleton tables** (e.g. `site_settings`, `chatbot_settings`, `voice_settings`,
    `review_settings`) always have `id = 1`.
  - **Slugs** are unique URL-friendly identifiers used wherever a row is exposed publicly
    (`gallery_cards.slug`, `services.slug`, `events.slug`, `blog_posts.slug`,
    `custom_forms.slug`, `page_sections.slug`).
  - **Sort order** columns named `sort_order` are used for drag-and-drop ordering.
  - **Encrypted columns** (`agent_provider_settings.api_key`, integration credentials) use a
    Fernet key derived from `FLASK_SECRET_KEY`. Always read/write through the encryption helpers
    in `app.py`.
- **Always** parameterize. Never `f"..."` user input into SQL.
- **Cost ledger writes** (`api_cost_events`, `voice_cost_events`, `sms_cost_events`) **stamp the
  unit price at write time** — historical rows must never be retroactively re-priced.
  SMS rows can be re-priced from a status webhook by multiplying the **stamped** unit price by the
  revised segment count, and only that.

---

## 9. Data Model Overview (by Domain)

All tables are created in `app.py`'s `init_db()`. Helper modules (`messaging.py`,
`automations.py`, `scraper.py`) reuse them — they do not own any tables.

### Core content / site
| Table | Purpose |
| --- | --- |
| `site_settings` | Singleton: site name, hero text/image, logo initials, theme toggles, business info, social links |
| `site_themes` | Saved color + font palettes |
| `site_designs` | Full HTML snapshots of homepage variants (admin can swap) |
| `page_sections` | Registry of every landing-page section (built-in + custom), order, enabled flag, template |
| `custom_section_items` | Items inside a custom section (cards, features, stats) |
| `gallery_cards` | Immersive gallery slides + landing-page highlight cards |
| `experiences` | Curated activity / feature cards |
| `pricing_seasons` | Seasonal pricing tiers |
| `faqs` | FAQ accordion items |
| `team_members` | Team / about cards |
| `video_gallery_items` | Video gallery |
| `podcast_episodes` | Podcast episode list |
| `uploaded_images` | Central media library row for every uploaded file (image / video / audio / contract) |

### AI & chat
| Table | Purpose |
| --- | --- |
| `chatbot_settings` | Singleton: personality, model, system prompt, greeting, suggested questions, agent_scope_tightness |
| `chat_conversations` | One row per visitor session (IP, device, started_at) |
| `chat_messages` | Every message; `tool_calls_json` JSONB logs each lookup tool invocation per turn |
| `generated_pages` | AI-generated HTML pages saved to the page library |
| `presentations` / `presentation_slides` | AI-narrated slide decks |
| `agent_skills` | Registry of every tool the agent can call (built-in + custom + remote) |
| `agent_provider_settings` | Encrypted credentials + model selection per AI provider |
| `custom_knowledge_entries` | RAG snippets the agent can pull from |
| `mcp_servers` / `mcp_tools_cache` | Remote MCP server connections + cached tool defs |
| `custom_webhook_skills` | User-defined HTTP-call tools |
| `custom_sql_skills` | User-defined read-only SQL tools (run with `SELECT`-only / `statement_timeout=5s` / 100-row cap) |
| `admin_chat_messages` | Admin AI conversation history |
| `admin_pending_actions` | Admin AI actions awaiting human approval |

### Voice
| Table | Purpose |
| --- | --- |
| `voice_settings` | Singleton: TTS/STT providers, default voice, `premium_enabled` master toggle |
| `voice_intros` | UTM-targeted welcome intro audio (matched by source/medium/campaign/referrer with priority tie-break) |
| `voice_usage_log` | Per-call telemetry for billing / cost rollup |

### Commerce / services / bookings / store
| Table | Purpose |
| --- | --- |
| `services` | Bookable services (pricing model, duration, calendar required, contract template) |
| `service_addons` | Optional priced extras |
| `service_availability_rules` | Recurring weekly slots |
| `service_availability_overrides` | Per-date `block` / `open` overrides |
| `service_bookings` | Individual bookings (snapshot of price + addons + payment + contract status) |
| `products` | Storefront catalog |
| `customers` | Storefront customer profiles |
| `orders` / `order_items` | Storefront orders + line items |

### Events & RSVPs
| Table | Purpose |
| --- | --- |
| `events` | Public event listings (free / paid / donation) |
| `event_rsvps` | Attendee sign-ups; capacity reserved at row creation; `payment_status` flips via Stripe webhook |

### Forms & reviews
| Table | Purpose |
| --- | --- |
| `custom_forms` | Form definitions (incl. **managed** `service_booking` forms tied to a service) |
| `form_fields` | Field definitions; `step` controls multi-step grouping |
| `form_submissions` | Submissions, including UTM/session tracking; partials promote to `new` on completion |
| `testimonials` | Curated on-site reviews |
| `review_destinations` | External review sites (Google / Yelp / TripAdvisor / custom) |
| `review_requests` | Outgoing ask emails/SMS with unique `/r/<token>` short link |
| `external_reviews` | Cached reviews pulled from third-party APIs |
| `review_settings` | Singleton: when/how to send asks |

### Scraping
| Table | Purpose |
| --- | --- |
| `scrape_jobs` | One row per scrape execution (input mode, target, raw + parsed output, status) |
| `scrape_schedules` | Recurring scrape config (cron-style + auto-pause counter) |
| `external_data_connections` | Encrypted external Postgres / REST sources for custom dashboards |

### Messaging & automations
| Table | Purpose |
| --- | --- |
| `subscribers` | Mailing list (email + phone, opt-in flags) |
| `messaging_templates` | Reusable email/SMS bodies with merge tags |
| `messaging_campaigns` | Bulk send batches |
| `messaging_log` | Per-message delivery record (provider id, status, opens, clicks) |
| `automations` | Workflow definitions (triggers + steps) |
| `automation_runs` | Per-execution log |
| `automation_versions` | Historical versions of each automation |
| `automation_settings` | Global engine config (concurrency, retention) |
| `automation_webhook_rejections` | Bad/incoming webhook ingress log |

### Cost tracking
| Table | Purpose |
| --- | --- |
| `model_prices` | Admin-editable unit prices (per million tokens / chars / minute / segment), `active` flag |
| `api_cost_events` | LLM cost ledger (prompt+completion tokens × stamped per-token unit price) |
| `voice_cost_events` | TTS chars × per-million OR STT seconds × per-minute |
| `sms_cost_events` | SMS segments × per-segment, deduped by `UNIQUE (tenant_id, message_sid)` |
| `tenant_cost_caps` | Per-tenant `monthly_cap_usd`, `warn_at_percent`, `cap_behavior`, alert/digest emails |
| `cost_alerts` | Idempotency log: `(tenant_id, period, kind)` UNIQUE |
| `weekly_digest_sends` | Idempotency log for the weekly digest claim-then-send |
| `skill_usage_log` | Per-tool invocation counts |

### Analytics / insights / dashboards
| Table | Purpose |
| --- | --- |
| `page_views` | Visitor analytics (UTM, device, browser, OS, referrer, duration) |
| `marketing_insights_log` | Cached AI-generated insight summaries |
| `dashboards` / `dashboard_widgets` | Custom admin KPI dashboards |
| `admin_setting_snapshots` | Version history of site settings (admin Recent Changes / rollback) |

### Infrastructure / multi-tenancy / sphere
| Table | Purpose |
| --- | --- |
| `plans` | Subscription tier definitions |
| `tenants` | Site instances |
| `tenant_features` | `(tenant_id, feature_name) → enabled` flags (lazy-seeded from `_FEATURE_REGISTRY`) |
| `feature_addons` | Per-tenant overrides |
| `sphere_settings` / `sphere_images` | 3D Sphere View config + image assets |

> If the table you need isn't listed, search `app.py` for `CREATE TABLE IF NOT EXISTS` to find it.

---

## 10. Backend Route Map

There are ~370 `@app.route` decorators in `app.py`. They follow strict prefix conventions:

| Prefix | Auth | Purpose |
| --- | --- | --- |
| `/` | none | Public landing page (`serve_index`); injects SEO meta + JSON-LD into `public/index.html` |
| `/blog/<slug>`, `/event/<slug>`, `/booking/<token>/...` | none | Public SEO-friendly subpages |
| `/r/<token>` | none | Public review-request short link (records `clicked_at`, optional `?r=` for `converted_at`) |
| `/sitemap.xml`, `/robots.txt` | none | SEO basics |
| `/api/*` | none | Public read-only JSON for the public site (`site-settings`, `gallery-cards`, `experiences`, `pricing`, `services`, `services/<slug>/availability`, `events`, `blog`, `team`, `faq`, `testimonials`, `business-info`, `page-sections`, `sphere-settings`, `video-gallery`, `podcast`, `products`, `storefront-config`, `forms/<slug>`, `review-snapshots`, ...) |
| `/api/forms/<slug>/submit`, `/api/forms/<slug>/partial` | none | Form submission + auto-save |
| `/api/services/<slug>/book`, `/api/services/<slug>/booking-partial` | none | Booking dispatcher (returns `redirect` / `contract_upload` / `rsvp_confirmed`) |
| `/api/chat` | none | Streaming SSE chat completion with the visitor concierge |
| `/api/voice/*` | none | TTS / STT / intros (see [§14](#14-voice-subsystem)) |
| `/admin/login`, `/admin/logout` | password | Auth |
| `/admin` | session | Admin dashboard HTML |
| `/admin/api/*` | session | Admin JSON CRUD — every content table has at least `GET / POST / PUT / DELETE` here |
| `/admin/api/chat/{send,stream,history}`, `/admin/api/chat/action/<id>/approve` | session | Admin AI chat + pending action approval |
| `/admin/api/cost/{summary,series,by-surface,by-model,prices,cap}` | session | Cost dashboard endpoints |
| `/admin/api/scrape-schedules/<id>/resume` | session | One-click resume after auto-pause |
| `/admin/api/services/<id>/contract-template` | session | Upload base contract for a `contract`-pricing service |
| `/api/stripe/webhook` | signature | `checkout.session.completed/.expired` — routes by `metadata.kind` (`service_booking`, `event_rsvp`, `order`, `donation`) |
| `/webhooks/resend` | optional signature | Email open/click/bounce/delivery events |
| `/webhooks/twilio/inbound-sms` | signature | Inbound SMS routed to the AI agent |
| `/webhooks/twilio/sms-status` | signature | Outbound SMS status updates (re-prices `sms_cost_events` rows) |
| `/automations/hook/<token>` | none (token in URL) | Public ingress for automations webhook triggers (gated by `automations` feature flag) |

### Feature-flag route gate

`@app.before_request` runs `_enforce_feature_flags()` against `_FEATURE_ROUTE_PREFIXES` (in
`app.py`). When a tenant doesn't have a feature:

- Public GET routes return **404** (no leak of feature names).
- Other requests return **403** with `{"error": "feature_disabled", "feature": "...", ...}`.

See [§24](#24-feature-flags--their-behavior-when-off) for the prefix → feature map.

### Cost-cap route gate

Paid surfaces call **`enforce_cost_cap(surface=...)`** before paying the provider. In
`strict_block` mode this returns **HTTP 402** with `{"error": "cap_reached", "spent": ..., "cap": ...}`.
In `throttle` mode it sets `g._cost_throttled = True`, which (a) downgrades the visitor chat rate
limit to 5 req/window, and (b) forces TTS to fall back from ElevenLabs to OpenAI.

---

## 11. Frontend Overview (`public/`)

### `public/index.html`

Single page with two top-level views:

- **Landing view** (`#landing-view`) — CSS scroll-snap; sections in DOM order: hero, highlights,
  experiences (incl. pricing), services, testimonials, team, FAQ, blog, events, video gallery,
  podcast, store, business info / contact, footer. Every section's enabled flag and order comes
  from the `page_sections` table; `applySectionOrder()` in `script.js` reorders DOM nodes at runtime.
- **Gallery view** (`.gallery-view`) — fullscreen immersive slides with wheel/swipe/keyboard
  navigation, dot nav, slide counter.
- Inquiry / service-booking / store-checkout / video-lightbox modals.
- `<!-- SEO_META_INJECT -->` and `<!-- JSON_LD_INJECT -->` placeholders are replaced at request
  time by Flask (`_build_seo_meta_html`, `_build_json_ld`).

CDN libs: Lucide, Three.js + CSS3DRenderer, DOMPurify, Stripe.js.

### `public/script.js`

- `loadAllData()` fetches all `/api/*` endpoints in parallel on page load, then runs `renderXxx()`
  for each section.
- View switching: `showGallery()`, `showSphereView()`, `showServiceModal()`, `openModal()`,
  `closeServiceModal()`.
- Gallery navigation: wheel cooldown 800 ms, touch swipe, arrow keys.
- AI chat overlay: shared with the AI concierge — handles streaming SSE from `/api/chat`,
  markdown rendering (sanitized via DOMPurify), command actions (`generatePage`, `showSlide`,
  `scrollToSection`, etc.), live page render (sandboxed iframe, postMessage chunk-streaming).
- Stripe Elements wiring for the storefront cart drawer.

### `public/voice.js`

`VoiceAgent` module exposes:
- `streamSpeakBegin()` / `streamSpeakFeed(token)` / `streamSpeakEnd()` / `streamSpeakCancel()` —
  parallel sentence detector + sequential audio queue (see [§14](#14-voice-subsystem)).
- `playIntro()` — fetches `/api/voice/intro`, picks the best UTM-matched audio.
- STT dispatch — Web Speech if available + selected, else MediaRecorder → `/api/voice/stt`.
- Bubbles get `__voiceStreamSpoken=true` so the legacy whole-message TTS hook
  (`chat:agent-message`) doesn't double-speak.

### `public/styles.css`

Numbered sections (search for `/* ===` comments). Theme tokens are CSS variables on `:root`
(`--color-accent`, `--font-serif`, `--bg-section-1`, `--glass-bg`, etc.) and are written by the
Theme Editor. Custom properties use **HSL with space-separated H S% L%** (no `hsl()` wrapper) —
the Tailwind-style convention even though we don't use Tailwind in the public site.

Scroll mode is set on `<html data-scroll-mode="snap|smooth">` from `siteSettings.scroll_mode`.

---

## 12. Admin Dashboard Overview

Single big Jinja template: `templates/admin/dashboard.html`. The sidebar is grouped — each tab is a
`<div class="tab-content" id="tab-...">`. Tabs are gated by feature flags via the `has_feature`
template helper.

| Group | Tabs |
| --- | --- |
| Insights | Overview · Custom Dashboards |
| Layout | Page Layout (drag-reorder + custom-section builder) · Theme Editor |
| Content | Site Settings · Gallery Cards · Experiences · Pricing · Business Info · Testimonials · Team · FAQ · Blog · Events · Services · Saved Pages · Web Scraper · Media Library · Video Gallery · Podcast |
| Store | Products · Orders · Sphere View |
| AI & Chat | Admin Chat · Chatbot · Chat History · Voice Agent · Forms |
| Marketing | SEO · Analytics · Marketing Insights |
| Site | Themes · Website Designs |
| Messaging | Subscribers · Templates · Campaigns |
| Automation | Automations |
| Reviews | Destinations · Requests · Insights |
| Other | Presentations · Skills Registry · Custom Skills · MCP Connectors · Recent Changes · AI Provider |
| System | Plans & Features · Cost |

**Admin Chat tab**: talks to the Admin AI which can mutate site state. Destructive actions land in
`admin_pending_actions` and require a human Approve click before being applied.

---

## 13. AI Subsystem (Visitor Chat & Admin Chat)

### Visitor chat (`POST /api/chat`)

Streaming SSE. Per turn:

1. Build a **compact site index** system prompt: brand identity, theme tokens, full forms schema,
   the full landing-page layout (every section in order, enabled/disabled, scrollToSection target),
   a per-category list of just **slugs + names** of every gallery card / service / experience /
   pricing tier / product / event / blog post / team member / FAQ / testimonial / generated page,
   plus the TOOL USAGE block. **Bulky descriptions/details/body text are NOT in the prompt** —
   they come from on-demand tool calls.
2. Append the conversation history (`chat_messages` for this `chat_conversations` row).
3. Call the LLM (OpenAI via Replit AI Integrations proxy by default; Anthropic if configured) with
   the active tool list and stream tokens back.
4. **Tool-call loop**, capped at **4 rounds per turn** (`MAX_TOOL_ROUNDS`):
   - Accumulate visible reply tokens AND tool-call deltas.
   - When `finish_reason == "tool_calls"`, dispatch each call via `execute_chat_tool()`,
     append `role=assistant` (with the tool call) + `role=tool` (with results) to messages,
     and re-stream.
5. Persist the assistant message; **log every tool call** (name, args, row count, duration) into
   `chat_messages.tool_calls_json` (JSONB) so the admin can see what data the AI pulled.

The lookup tools (defined in `CHAT_TOOLS`, dispatched via `CHAT_LOOKUP_FUNCTIONS`):

`lookup_gallery_cards`, `lookup_services`, `lookup_service_availability`, `lookup_experiences`,
`lookup_pricing`, `lookup_products`, `lookup_events`, `lookup_blog`, `lookup_team`, `lookup_faq`,
`lookup_testimonials`, `lookup_business_info`, `lookup_custom_section_items`,
`lookup_generated_page`, `lookup_presentation`, `lookup_web_search`.

> The `web_search` tool is gated by the `web_search` feature flag and `BRAVE_SEARCH_API_KEY`.
> `replit.md` historically described **14** tools; the code currently exposes **16**.

### Custom skills

Three kinds, all surfaced as agent tools:

1. **Webhook skills** (`custom_webhook_skills`) — call an external HTTP endpoint with a JSON
   schema-defined arg shape.
2. **SQL skills** (`custom_sql_skills`) — `SELECT`-only single statement, 100-row cap, 5-second
   `statement_timeout`, runs in a non-autocommit connection that's always rolled back. Args bind
   via `psycopg2` named placeholders (`%(name)s`) so they can never be interpolated as SQL.
3. **MCP connectors** (`mcp_servers`, `mcp_tools_cache`) — remote Model Context Protocol servers.
   Tool definitions are cached locally and dispatched as if they were local tools.

### Admin chat

`POST /admin/api/chat/{send,stream}`. Same loop, different system prompt — the admin AI knows it
can mutate site state but routes destructive operations through `admin_pending_actions`.

### Agent scope slider

`chatbot_settings.agent_scope_tightness ∈ {strict, balanced, generous}`. Appends a paragraph to
the system prompt that nudges how proactive / expansive the agent should be. Gated by the
`agent_scope_slider` feature flag (no-op when off).

---

## 14. Voice Subsystem

### Streaming TTS (two-step handshake)

1. **`POST /api/voice/tts/stream/prepare`**: validate permission, per-IP daily cap, cost cap; if
   the `(model, voice, text)` SHA-1 already exists in `uploads/voice/`, return `audio_url` for the
   cached MP3. Otherwise mint a one-shot opaque token and return a `stream_url` so the synthesized
   text never appears in a GET.
2. **`GET /api/voice/tts/stream/consume?token=...`**: opens the provider stream (OpenAI or
   ElevenLabs), pipes bytes to the browser, and tees them to a `.part` temp file that's atomically
   `os.replace`-d into the cache on success (and removed on disconnect/error).

### Per-sentence streaming during chat

`public/voice.js`:

- `streamSpeakBegin/Feed/End` accumulate streamed AI tokens, detect sentence boundaries
  (`.!?` + whitespace, with abbreviation guards: `Mr.`, `Dr.`, `etc.`, `e.g.`, ...).
- Each completed sentence fires its own `/prepare` immediately (parallel).
- `runStreamQueue` plays them in **reading order** (sequential).
- Capped at first 4 sentences (`MAX_SPOKEN_SENTENCES`) to avoid long monologues.
- Bubbles tagged `__voiceStreamSpoken=true` so the legacy whole-message TTS path
  (`chat:agent-message`) doesn't double-speak.

### STT

- **Web Speech API** (browser-native): instant, free, accuracy varies.
- **OpenAI Whisper-1** (`/api/voice/stt`): MediaRecorder records `.webm`/`.mp4`, server forwards to
  Whisper with `response_format="verbose_json"` so we get accurate `audio_seconds` for billing.
- Fallback chain: chosen provider → other provider on failure → mic-denied disables both.

### Providers

| Provider | When used | Notes |
| --- | --- | --- |
| OpenAI TTS (`tts-1`) | Default | Cheap, fast, six voices |
| ElevenLabs | Premium | Requires `voice_settings.premium_enabled=true` AND `ELEVENLABS_API_KEY`; **auto-falls back to OpenAI when the request is cost-throttled** |

### Caching

SHA-1 of `model|voice_id|text` → `uploads/voice/<hash>.mp3`. Identical text+voice across visitors
shares the file.

### Per-IP daily caps

`TTS_DAILY_CHARS_PER_IP` (~30k char default), `STT_DAILY_REQUESTS_PER_IP` (~100). In-memory dict
keyed by `(ip, YYYY-MM-DD)` — resets at midnight (process-local; no Redis).

### Routes under `/api/voice/*`

| Path | Method | Purpose |
| --- | --- | --- |
| `/api/voice/settings` | GET | Public toggles, default voice, configured providers |
| `/api/voice/intro` | GET | UTM-matched welcome audio |
| `/api/voice/tts` | POST | Legacy non-streaming TTS (kept for admin pre-generation) |
| `/api/voice/tts/stream/prepare` | POST | Streaming step 1 |
| `/api/voice/tts/stream/consume` | GET | Streaming step 2 |
| `/api/voice/stt` | POST | Whisper transcription |
| `/api/voice/sample` | POST | Admin-only voice audition clip |
| `/api/voice/log` | POST | Browser-side telemetry (Web Speech events, etc.) |

---

## 15. Commerce — Services, Bookings, Events, Store

### Services (`services`, `service_addons`, `service_availability_*`, `service_bookings`)

Pricing models on `services.pricing_model`:

| Model | Behavior |
| --- | --- |
| `rsvp` | Free reservation; `rsvp_confirmed` returned to frontend, no payment |
| `deposit` | Stripe Checkout for the deposit amount; remainder owed offline |
| `full` | Stripe Checkout for full price |
| `contract` | Admin uploads a PDF/DOC/DOCX template; client downloads, signs offline, re-uploads at `/booking/<token>/contract` |

**Add-ons** (`service_addons`): multi-selectable at booking time; the chosen set is **snapshotted**
on the booking row so totals stay stable even if the addon is later edited/removed.

**Availability** (calendar-backed services with `requires_calendar=true`):

`/api/services/<slug>/availability?start&end` computes:

```
slots = (recurring rules ∪ open overrides)
      − block overrides
      − slots already filled to capacity_per_slot by pending/confirmed bookings
```

Capacity is reserved on row creation so the slot disappears for other visitors during Checkout.
Successful payment OR an admin status flip to `confirmed` removes the slot for future visitors.

**Booking dispatcher** (`/api/services/<slug>/book`) returns one of:

- `{ "action": "redirect", "url": "<stripe_checkout_url>" }`
- `{ "action": "contract_upload", "url": "/booking/<token>/contract" }`
- `{ "action": "rsvp_confirmed", "booking_id": ... }`

**Stripe webhook routing**: `/api/stripe/webhook` looks at
`session.metadata.kind` to dispatch:

| `metadata.kind` | What happens |
| --- | --- |
| `service_booking` | Flip `payment_status='paid'`, `status='confirmed'`, record `stripe_session_id` + `amount_paid_cents` |
| `event_rsvp` | Flip `event_rsvps.payment_status='paid'`; `expired` on session expired |
| `order` | Flip storefront `orders.status='paid'` |
| `donation` | Flip `event_rsvps.payment_status='paid'` for donation events (visitor-entered amount, optional minimum) |

All handlers are **idempotent** — `FOR UPDATE` row locks + status checks.

### Events (`events`, `event_rsvps`)

Three modes via `events.price_mode`:

- `free` — RSVP only.
- `paid` — Stripe Checkout for fixed `price_cents × guests`.
- `donation` — Visitor-entered amount (optional minimum), "pay what you wish".

Free RSVPs save instantly. Paid/donation RSVPs save with `payment_status='pending'` and reserve
capacity, then redirect to Checkout. The webhook flips them to `paid` (or `expired`).

### Store (`products`, `customers`, `orders`, `order_items`)

Frontend cart drawer uses Stripe.js + Elements (`STRIPE_PUBLISHABLE_KEY`).
PaymentIntent confirmation; webhook flips `orders.status='paid'`.

---

## 16. Forms Subsystem

- **Builder**: admin Forms tab. Field types: text/email/phone/textarea/select/radio/checkbox/file/
  date. Multi-step via `form_fields.step`.
- **Submission**: `POST /api/forms/<slug>/submit` writes to `form_submissions`.
- **Partial / abandon capture**: `POST /api/forms/<slug>/partial` (debounced ~800 ms once an email
  is typed) UPSERT-keyed by per-tab `session_id` so the same visitor's abandoned cart **promotes**
  to a `new` submission on completion (no duplicate rows).
- **Marketing analytics fields** persisted on every submission/partial: `session_id`, `page_url`,
  `referrer`, `language`, `screen_resolution`, `utm_source`, `utm_medium`, `utm_campaign`,
  `utm_term`, `utm_content`.
- **Managed forms**: every service auto-mirrors its bookings into the Forms tab via a
  `custom_forms` row with `form_type='service_booking'`, `linked_service_id=<service.id>`,
  slug `service-booking-<svc-slug>`. Created lazily by `_ensure_service_booking_form()` on the
  first booking attempt. Edit/Delete and field-mutation endpoints are blocked server-side
  (`_reject_if_managed`); a purple "Service Booking" badge marks them in the UI.

---

## 17. Reviews Subsystem

- **Destinations** (`review_destinations`): external sites (Google / Yelp / TripAdvisor / custom).
  `public_visible` rows are exposed via `/api/review-snapshots` for the public site.
- **Requests** (`review_requests`): outgoing ask emails/SMS. Each carries a unique
  **`/r/<token>`** short link that records `clicked_at` on click and `converted_at` when an
  internal review form is submitted with `?r=<token>`.
- **AI drafting**: `gpt-4o-mini` writes a short personalized message using the recipient's name and
  what they bought/booked; that message is wrapped in an admin-selected `messaging_templates` body
  so brand/tone stays consistent.
- **Triggers**:
  - Manual buttons on order detail / form-submission detail pages.
  - Scheduler sweep: auto-queues asks N days after `orders.status='paid'` or
    `event_rsvps.payment_status='paid'`.
- **Snapshot scheduler**: nightly tick caches aggregate ratings (count + avg) per destination via
  Google Places, Yelp Fusion, TripAdvisor Content APIs. Gated by
  `GOOGLE_PLACES_API_KEY` / `YELP_API_KEY` / `TRIPADVISOR_API_KEY`.
- **Settings**: `review_settings` (singleton).

---

## 18. Scraping Subsystem (`scraper.py`)

- **Two input modes**:
  - **URL** — server-side `requests.get` with **SSRF guards**: deny private/loopback/link-local IPs
    after DNS resolution, **5 MB cap**, content-type allowlist, **redirect re-validation** at every
    hop.
  - **Objective** — uses OpenAI Responses API with the `web_search_preview` tool.
- **Output shaping**: cleans HTML to text and asks GPT (JSON mode) to produce one of: free-form
  notes / gallery card / pricing tier / blog post / contact details / custom JSON schema.
  Results can be pushed as **drafts** into the matching tables.
- **Schedules** (`scrape_schedules`): cron-style hourly/daily/weekly/interval (UTC). Email/SMS the
  admin on completion or only on **change** (signature comparison). Auto-pause after
  `failure_threshold` consecutive failures (default 5; 0 disables). Resume via
  `POST /admin/api/scrape-schedules/<id>/resume`.
- **Rendered fetch fallback**: when a plain GET response looks JS-only and the admin enabled the
  toggle, retry through ScrapingBee or Browserless. Provider chosen by `SCRAPER_RENDER_PROVIDER`
  (default `scrapingbee`); credentials from `SCRAPINGBEE_API_KEY` or
  `BROWSERLESS_TOKEN`/`BROWSERLESS_URL`. The target URL is SSRF-validated **before** being handed
  to the provider; response is still size-capped.

---

## 19. Automations Subsystem (`automations.py`)

- **Workflow definition**: `automations` row with a trigger (form submission, schedule, webhook
  POST to `/automations/hook/<token>`, etc.) and an ordered list of steps.
- **Step kinds** (the seven "Common actions" plus `call_skill` for any registered skill or
  integration). Step args support **merge tags** like `{{trigger.fields.email}}`, `{{step1.text}}`,
  `{{step_<name>.status}}`, recursively rendered into nested dicts/lists.
- **Run records**: every execution writes to `automation_runs` (status, durations, per-step
  output). `automation_versions` stores historical versions.
- **Concurrency / safety limits** (env-tunable): `AUTOMATIONS_MAX_CONCURRENT`,
  `AUTOMATIONS_MAX_PER_HOUR`, `AUTOMATIONS_MAX_RUN_SECONDS`, `AUTOMATIONS_HTTP_TIMEOUT`,
  `AUTOMATIONS_DELAY_MAX`, `AUTOMATIONS_AI_TIMEOUT`.
- **Retention**: `AUTOMATIONS_RETENTION_DAYS` + `AUTOMATIONS_RETENTION_KEEP_RECENT` — sweep deletes
  old `automation_runs` while always keeping the N most recent.
- **Webhook ingress**: `/automations/hook/<token>` — public, gated by `automations` feature flag
  (so disabling it returns 404 to third-party callers instead of silently consuming POSTs).
  Bad/rejected ingress goes to `automation_webhook_rejections`.

---

## 20. Notifications (`messaging.py`)

- **Always** send through `messaging.send_email(...)` and `messaging.send_sms(...)` — they handle:
  opt-out check, template merging, `messaging_log` insert, provider call, status-webhook stitching.
- **Email** via Resend: `RESEND_API_KEY` + `RESEND_FROM_EMAIL`. Open/click/bounce events come back
  on `/webhooks/resend` (signature optional via `RESEND_WEBHOOK_SECRET`).
- **SMS / WhatsApp** via Twilio: `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` +
  `TWILIO_FROM_NUMBER`. Status updates on `/webhooks/twilio/sms-status` (re-prices
  `sms_cost_events` rows by stamped unit price × revised segment count). Inbound SMS on
  `/webhooks/twilio/inbound-sms` is routed to the AI agent.
- **Opt-out**: STOP keyword handling. Subscribers in `subscribers` flip to opted-out.
- **Cost**: every send writes to `sms_cost_events` (deduped by `UNIQUE (tenant_id, message_sid)`).

---

## 21. Cost Transparency & Weekly Digest

Implemented in `app.py` under the **COST TRANSPARENCY (Phase 2)** section.

### Three ledgers (stamp price at write time)

| Table | Records |
| --- | --- |
| `api_cost_events` | LLM (prompt + completion tokens × per-token unit price) |
| `voice_cost_events` | TTS chars (per-million chars) OR STT seconds (per-minute) |
| `sms_cost_events` | SMS segments (per-segment), `UNIQUE (tenant_id, message_sid)` |

### `model_prices`

Admin-editable table of unit prices per `(provider, model, surface)`. Cached in-process (`_PRICE_CACHE`) for **60 seconds**.
Edits **never** retroactively re-price already-stamped rows.

### `tenant_cost_caps.cap_behavior` (three modes)

| Mode | Behavior |
| --- | --- |
| `alert_only` | Never blocks/throttles. Only fires warn-line emails. |
| `throttle` | Never blocks. Sets `g._cost_throttled = True` → chat rate limit drops to 5 req/window; TTS auto-falls back ElevenLabs → OpenAI. |
| `strict_block` | Returns **HTTP 402** `{"error":"cap_reached","cap":..,"spent":..}` on every paid call until the next month rolls. |

Two enforcement entry points:

- `enforce_cost_cap(surface=...)` — HTTP request paths (chat, voice).
- `cost_cap_blocks_send(surface=..., tenant_id=...)` — background jobs (SMS campaign sends, scrape
  notifications, review-request SMS). Returns `True` only when `strict_block`.

### `cost_alerts`

Idempotency log with `UNIQUE (tenant_id, period, kind)` — admin gets emailed exactly once per
month per "warn" / "cap" event.

### Weekly digest (`weekly_digest_sends`)

Scheduler tick fires every Monday 09:00–09:30 UTC:

1. **Claim** the slot first:
   ```sql
   INSERT INTO weekly_digest_sends (tenant_id, week_start, payload_json)
   VALUES (...)
   ON CONFLICT (tenant_id, week_start) DO NOTHING
   RETURNING id
   ```
2. Only if a row was returned, render `_digest_render_html()` ("What your AI did this week" — spend,
   per-surface breakdown, top conversations, top forms) and email via Resend to
   `cap.digest_email` → `cap.alert_email` → `ADMIN_EMAIL`.

This claim-then-send order means a crash mid-send can never double-deliver.

### Feature flags

- `cost_dashboard` — gates the **Cost** tab and the `enforce_cost_cap` calls.
- `weekly_digest` — gates the digest scheduler tick.

### Endpoints

`/admin/api/cost/{summary,series,by-surface,by-model,prices,cap}` (GET / PATCH / PUT,
`@admin_required` + `_cost_feature_required()` returns 404 when the flag is off).

---

## 22. Analytics

- `page_views`: every page load. Captures `session_id`, `visitor_id`, `page_url`, `referrer_url`,
  five `utm_*` fields, `ip_address`, `browser`, `os`, `device_type`, `screen_resolution`,
  `language`, `country`, `duration_seconds`.
- Admin **Analytics** tab visualizes views, unique visitors, devices, browsers, top referrers,
  UTMs, session duration via Chart.js.
- **Marketing Insights** tab caches AI-generated summaries (chat topics, content gaps, drafted
  blog/FAQ awaiting approval) in `marketing_insights_log`.
- Form submissions also ship UTM + session metadata (see [§16](#16-forms-subsystem)).

---

## 23. Security & Safety

- **SSRF**: `scraper.py` resolves the host, denies private / loopback / link-local IPs **after**
  DNS resolution, re-validates on every redirect hop, caps response at 5 MB, and enforces a
  content-type allowlist. The same checks gate ScrapingBee/Browserless target URLs.
- **SQL injection**: every query uses `%s` (or `%(name)s` for SQL skills). No `f"..."`.
- **Stored secrets**: `agent_provider_settings` and other credential rows are encrypted with
  Fernet, key derived from `FLASK_SECRET_KEY`. Plaintext is only in-memory.
- **Rate limits**: in-process token buckets keyed by IP. See [§7](#7-authentication-sessions--rate-limits).
- **HTML sanitization**: every AI-generated HTML / markdown render in the public chat passes
  through **DOMPurify** before `innerHTML`.
- **Generated pages** render in a **sandboxed iframe** (`sandbox="allow-scripts"`) with theme
  variables + hero image auto-injected into `:root`. Streaming HTML chunks are appended via
  `postMessage` (the sandbox blocks direct DOM access from the parent).
- **Webhook signatures**: enforced for Stripe, Twilio (SMS in/out), and optionally Resend.
- **Admin actions with side effects** (Admin AI mutations, sends, deletes) route through
  `admin_pending_actions` and require a human Approve click.
- **Service bookings** lock rows `FOR UPDATE` during webhook flips so two webhook deliveries can't
  double-confirm.

---

## 24. Feature Flags & Their Behavior When Off

Source of truth: `_FEATURE_REGISTRY` in `app.py`. Each entry is
`(feature_name, human_label, plan_tier_required, default_enabled, group)`.

| Feature | Plan tier | Default | Group |
| --- | --- | --- | --- |
| `website_builder` | solo | on | Website |
| `site_themes` | solo | on | Design |
| `site_designs` | growth | on | Design |
| `deck_launch` | growth | on | AI |
| `web_search` | growth | on | AI |
| `voice` | growth | on | AI |
| `generated_pages` | growth | on | AI |
| `agent_scope_slider` | growth | on | AI |
| `custom_forms` | solo | on | Capabilities |
| `mcp` | enterprise | on | Capabilities |
| `presentations` | growth | on | Capabilities |
| `automations` | growth | on | Capabilities |
| `messaging` | growth | on | Capabilities |
| `chat_history` | solo | on | Capabilities |
| `analytics` | growth | on | Analytics |
| `cost_dashboard` | growth | on | Analytics |
| `weekly_digest` | growth | on | Analytics |

Plus the master kill-switch `voice_settings.premium_enabled` for paid voice providers.

**Client carve-out (`CLIENT_MODE` env, May 2026).** `website_builder` is the first
member of `_OPERATOR_ONLY_FEATURES`. It defaults **on** (operator installs are
unchanged), but when `CLIENT_MODE` is truthy (`1`/`true`/`yes`/`on`) a block right
after `_FEATURE_DEFAULTS` flips every operator-only feature's default to **off**, so
a client install only sees the AI concierge — the website-builder admin surface
(themes/pages/SEO/sections/etc.) is gated off at the route layer. A per-tenant
`tenant_features` override still wins over the default, so an operator can re-enable
the builder for a specific client without changing env. The AI-referenced content
surfaces (`blog`/`team`/`faq`/`testimonials`/`experiences`/`pricing`/`business-info`)
and Marketing Insights (`/admin/api/marketing`) are deliberately **left on** for
clients.

### How "off" behaves

A `before_request` hook (`_enforce_feature_flags`) checks `request.path` against
`_FEATURE_ROUTE_PREFIXES`:

| Prefix | Feature |
| --- | --- |
| `/admin/api/analytics` | `analytics` |
| `/admin/api/automations` | `automations` |
| `/admin/api/chat-history` | `chat_history` |
| `/admin/api/forms` | `custom_forms` |
| `/admin/api/generated-pages` | `generated_pages` |
| `/admin/api/mcp/` | `mcp` |
| `/admin/api/messaging` | `messaging` |
| `/admin/api/presentations` | `presentations` |
| `/admin/api/site-designs` | `site_designs` |
| `/admin/api/site-themes` | `site_themes` |
| `/admin/api/voice` | `voice` |
| `/api/forms/` | `custom_forms` |
| `/api/generated-pages` | `generated_pages` |
| `/api/presentations/` | `presentations` |
| `/api/voice/` | `voice` |
| `/automations/hook/` | `automations` |
| `/admin/api/theme`, `/admin/api/curated-font-pairs`, `/admin/api/site-settings`, `/admin/api/page-sections`, `/admin/api/pages`, `/admin/api/custom-sections`, `/admin/api/section-visibility`, `/admin/api/seo`, `/admin/api/social-links`, `/admin/api/sphere-images`, `/admin/api/sphere-settings`, `/admin/api/video-gallery`, `/admin/api/podcast`, `/admin/api/reorder` | `website_builder` |

When the flag is off:

- **Public GET** (paths not starting with `/admin/`): return **404** `{"error":"not_found"}` so we
  don't leak feature names to anonymous visitors.
- **Anything else**: return **403** `{"error":"feature_disabled","feature":"...","message":"..."}`.

### Other helpers

- `tenant_has_feature(name)` — cached lookup (30 s TTL). **Unknown** flag names default to
  `True` so adding a new gate to code without a registry entry can never silently break prod.
- `list_tenant_features()` — drives the Plans & Features admin UI.
- `set_tenant_feature(name, enabled)` — flip from admin UI; invalidates cache.
- The `has_feature` template helper hides/shows admin tabs.
- Some features (e.g. `agent_scope_slider`) simply no-op (return `""`) when off.

---

## 25. External Integrations Summary

| Provider | Env vars | What breaks when missing |
| --- | --- | --- |
| **OpenAI (LLM)** via Replit AI Integrations | `AI_INTEGRATIONS_OPENAI_API_KEY`, `AI_INTEGRATIONS_OPENAI_BASE_URL` | Visitor + admin chat; AI page/blog/SEO/insights generation |
| **OpenAI (audio)** direct | `OPENAI_API_KEY` | Voice TTS (default provider) and Whisper STT |
| **Anthropic** | `ANTHROPIC_API_KEY` | Optional Claude alternative LLM |
| **ElevenLabs** | `ELEVENLABS_API_KEY` (+ `voice_settings.premium_enabled`) | Premium TTS; auto-falls back to OpenAI when cost-throttled |
| **Resend** | `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_WEBHOOK_SECRET` | All email sends; bounce/open/click events |
| **Twilio** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS/WhatsApp campaigns, STOP opt-out, inbound SMS, status webhook |
| **Stripe** | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | Service deposits/full pay, paid event RSVPs, donations, storefront orders |
| **Sentry** | `SENTRY_DSN`, `SENTRY_ENV` | Error monitoring |
| **ScrapingBee / Browserless** | `SCRAPER_RENDER_PROVIDER`, `SCRAPINGBEE_API_KEY` / `BROWSERLESS_TOKEN` + `BROWSERLESS_URL` | JS-rendered scraping fallback |
| **Google Places / Yelp / TripAdvisor** | `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY` | Reviews aggregator snapshots |
| **Brave Search** | `BRAVE_SEARCH_API_KEY` | `lookup_web_search` chat tool |
| **Replit Connectors** | `REPLIT_CONNECTORS_HOSTNAME`, `REPL_IDENTITY`, `WEB_REPL_RENEWAL` | Internal credential broker for managed integrations |

---

## 26. Conventions an Agent Must Follow When Editing

1. **Industry-agnostic naming.** No "hotel", "villa", "guest", "resort", "room" in code, comments,
   defaults, or docs. The template is reused across industries.
2. **Heavily commented, modular code.** Match the comment density in `public/index.html` /
   `script.js` — explain *why*, not just *what*.
3. **Use the helpers** — never bypass them:
   - DB → `query_db` / `execute_db` (parameterized).
   - Email/SMS → `messaging.send_email` / `messaging.send_sms`.
   - Stripe → `stripe_client.get_stripe_client()` (do not import `stripe` directly elsewhere).
   - Encryption → existing Fernet helpers in `app.py`.
   - Tenant resolution → `current_tenant_id()` (never hard-code `1`).
   - Rate-limit / cost-cap → `enforce_cost_cap()` / `cost_cap_blocks_send()` before every paid call.
4. **Schema changes** go in `init_db()` as `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN
   IF NOT EXISTS`. No separate migration file.
5. **New chat capability?** Register it in `CHAT_TOOLS` + `CHAT_LOOKUP_FUNCTIONS` and also
   document the slug/name pair in the compact site index builder so the AI knows it exists.
6. **New admin tab?** Add it to `templates/admin/dashboard.html` and gate it with
   `has_feature("...")` if it's behind a feature flag.
7. **New paid surface?** Register a row in `model_prices` and add the surface to the cost
   dashboard's surface enum + chart.
8. **Public site changes:** add `data-testid` to every interactive element and meaningful
   information element. Use the `{action}-{target}` / `{type}-{content}` / `{type}-...-${id}`
   patterns documented in the Fullstack-JS skill.
9. **Theme variables** in `:root`: HSL with **space-separated** `H S% L%` and no `hsl()` wrapper.
10. **Forbidden** without explicit approval: editing `package.json`, modifying `vite.config.*` or
    `drizzle.config.ts` (this project doesn't use Drizzle but the file convention is reserved),
    rewriting any of `app.py` from scratch, running git commands.
11. **Logs over silence.** When an upstream call fails, surface a clear error to the admin/visitor
    rather than a silent fallback — except where the existing code has explicitly chosen to
    fail-open (e.g. `RESEND_WEBHOOK_SECRET` placeholder behavior).

---

## 27. Placeholder Credentials & User-Visible Failure Modes

(Mirrors the **Credentials Status** block in `replit.md`. Update both files together when this
changes.)

Secrets present in this Repl but **still holding placeholder values** — the matching features will
fail or no-op until real values are pasted in:

| Placeholder secret | User-visible failure |
| --- | --- |
| `RESEND_WEBHOOK_SECRET` | Fail-open: webhook accepts events without signature check; status updates still post but anyone can spoof them |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS campaigns, STOP-keyword opt-out, and inbound-SMS webhook return errors until real Twilio creds are set |
| `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY` | Reviews aggregator (Reviews → Insights tab) returns empty / error responses for the matching providers |

Confirmed working with real values: `ADMIN_PASSWORD`, `ADMIN_EMAIL`, `ADMIN_PHONE`,
`FLASK_SECRET_KEY`, `ELEVENLABS_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `SENTRY_DSN`, plus
the Replit-managed integrations (OpenAI, Anthropic, Stripe, database).

When debugging or adding features that touch the placeholder list, **assume the upstream call will
fail and surface a friendly error** — don't gate new functionality on those features being live.

---

## 28. Pointers to Deeper-Dive Docs

- **`replit.md`** — the living changelog / feature-by-feature architecture detail (~86 KB).
  Search it (`rg "Feature Name" replit.md`) when you need the long-form story behind a feature.
- **`KEYS.md`** — per-install key reference: where provider keys (server env), embed keys
  (`tenant_embed_keys` rows, publishable + origin-restricted), and DB-stored secrets
  (Fernet from `FLASK_SECRET_KEY`) live, plus the provisioning checklist. Read before
  standing up a new client install.
- **`GUIDE.md`** — non-developer walkthrough of the admin dashboard.
- **`TEMPLATE_OVERVIEW.md`** — short feature overview (originally written when this was
  hospitality-flavored). Light on detail; this file supersedes it for agents.
- **`.local/tasks/*.md`** — per-feature task plans. When working on feature X, search there for the
  original plan and acceptance criteria.
- **`chat-ui-kit/README.md`, `chat-ui-kit/INTEGRATION_GUIDE.md`, `chat-ui-kit/PROMPT_GUIDE.md`** —
  docs for the standalone embeddable chat widget kit (separate from the live app).
- **`.local/skills/*/SKILL.md`** — Replit-provided agent skills (workflows, deployment, integrations,
  database, secrets, etc.). Read the relevant one before doing infra work.

---

## 29. Doc Drift

Anything below is a place where this knowledge base and `replit.md` (or `TEMPLATE_OVERVIEW.md`)
disagree with what the code actually does. **Trust the code.** Reconcile here when fixing.

- **Chat lookup tools — count.** `replit.md` historically mentions **14** lookup tools. The current
  `CHAT_TOOLS` registry exposes **16** — the additional ones are `lookup_service_availability`
  and `lookup_presentation`. The 4-round cap is unchanged.
- **`TEMPLATE_OVERVIEW.md`** still uses some hospitality-flavored examples ("villa", etc.). The
  active code is industry-agnostic; treat the overview as historical context.
- **`data.db`** at the repo root is an empty leftover from an old SQLite path. The live database
  is PostgreSQL via `DATABASE_URL`. Do not write to `data.db`.
- **Cross-project guardrails.** This project does not use Drizzle, Vite, or any JS bundler — the
  public site is plain HTML/CSS/JS served directly by Flask. The "do not edit `drizzle.config.ts`
  / `vite.config.*`" guardrails listed in [§26](#26-conventions-an-agent-must-follow-when-editing)
  are inherited from the platform-wide Fullstack-JS skill and will only matter if those files are
  added later.
- **Embed / WordPress-SSO surface (May 2026).** The cross-origin embeddable widget and the
  WordPress single-sign-on layer live **inline in `app.py`** (not in a separate module): the
  `tenant_embed_keys` + `sso_used_jtis` tables (created in `init_db()`), the
  `_embed_auth` before_request / `_embed_cors` after_request pair (scoped CORS — origin echoed
  from each key's allowlist, never `*`; preflight `OPTIONS` answered 204 without resolving the
  key), `/embed/loader.js`, `/widget/<file>` (allowlist `{chat-ui.js, chat-ui.css, voice.js}`),
  `/admin/api/embed-keys` CRUD, and `/admin/sso` (HMAC token verify → 302 /admin; 503 if
  `SSO_SIGNING_SECRET` unset; 403 forged/expired/replayed). The standalone
  `admin_ai_platform/` package is the *reference* implementation of this surface, not what the
  live app loads. New env vars: `CLIENT_MODE`, `SSO_SIGNING_SECRET`. Full long-form story:
  `replit.md` → "Client Mode + Embeddable Widget + WordPress SSO (Tier 11 — May 2026)".
- **Admin "Tabs"** list in `replit.md` predates several newer tabs (Cost, Plans & Features, Custom
  Dashboards, MCP Connectors, Custom Skills, Marketing Insights, Site Designs, Themes,
  Subscribers/Templates/Campaigns, Automations, Reviews split, Voice Agent, Services, Events,
  Video Gallery, Podcast, Products, Orders, Sphere View, Recent Changes, Admin Chat, Skills
  Registry, AI Provider). The full canonical list is in [§12](#12-admin-dashboard-overview).
