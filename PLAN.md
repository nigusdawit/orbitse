# PLAN — Extract the Admin/AI Platform into a Standalone, Embeddable Product

- **Status:** COMPLETE (M0–M9 merged to main, 2026-05-29)
- **Drafted:** 2026-05-29
- **Approved:** 2026-05-29
- **Completed:** 2026-05-29 — final gate 159/159 (embedded Postgres), ruff + unit + node clean,
  live server 6/6 public surfaces 200. Follow-ons (need live keys/services): full Stripe Checkout
  + product sync, live LLM/embedding/scrape-AI rounds, single-DB multi-tenant row scoping, the
  upstream 30-command VELO surface, and an in-browser/WordPress manual UX pass.
- **Full design doc:** `~/.claude/plans/tender-knitting-token.md` (canonical; this is the working mirror)
- **Task index:** `tasks/README.md`

---

## Goal

Carve the admin/AI half of the 38k-line `app.py` monolith (plus helper modules) into a new
self-contained Python package `admin_ai_platform/` that runs as its own Flask app and is distributed
as a **plugin** — a universal JS **embed snippet** and a **WordPress plugin** — so clients install it
into an existing site without touching code. The public marketing site and presentation-only web
editors are left behind in the original (untouched) `app.py`.

Deployment is config-switchable: **central** multi-tenant SaaS or **self_host**; admin is
**self_serve** (per-tenant login) or **agency_only**.

## Non-goals

- The public marketing website rendering (landing/sphere/blog/event public pages, SEO, sitemap,
  public read APIs) — stays in the original app.
- Presentation-only admin editors (Page Layout, Theme, Site Themes/Designs, Sphere, SEO, and the
  marketing-content tabs the AI does not reference) — not ported; their data tables still exist.
- Modifying the original `app.py` — **independent copy**, zero changes to the live app.

## Stack decisions

- Flask app-factory (`create_app()`) + blueprints per subsystem; psycopg2 raw SQL (no ORM).
- OpenAI **and** Anthropic for chat; OpenAI-direct + optional ElevenLabs for voice.
- PostgreSQL; schema bootstrapped by `schema.py` (subset of original `init_db()`), idempotent.
- Embed widget: cross-origin, **Shadow DOM** isolation; `generatePage` stays a sandboxed iframe.
- WordPress plugin: PHP — settings + auto-enqueue + shortcode/block + wp-admin embedded admin via SSO.
- Distribution/mode flags: `DEPLOY_MODE` (central|self_host), `ADMIN_MODE` (self_serve|agency_only).

## What's IN vs OUT, package tree, admin tabs kept/dropped, security model, key flows, env vars

See the full design doc (`~/.claude/plans/tender-knitting-token.md`). Summary:

- **IN:** visitor chat (tool loop, site index, generatePage, live render, chat lookup tools), admin AI
  (+approval), voice, cost (+caps+digest), skills/MCP, RAG/KB, automations, scraper, reviews,
  messaging, presentations, snapshot/VELO, multi-tenant, provider settings, dev console, secrets,
  analytics; plus the gallery/forms/media/commerce(services,products,events) editors the AI touches.
- **OUT:** public web rendering + presentation-only WEB-ADMIN editors (data tables kept, no UI/route).
- **Security (new trust boundary):** per-tenant publishable embed key + origin allowlist, scoped CORS,
  per-tenant rate limiting, admin auth separate from embed key, single-use HMAC SSO for WP admin iframe.

## Testing strategy (verification gate per task)

- **Unit (pytest):** command parse, site-index builder, tool dispatch, voice cache-key + per-IP cap,
  cost stamping/cap, automations trigger match, merge-tag render, scraper SSRF guard, RAG chunker.
- **Boot/import smoke:** `create_app()` imports with no dangling `from app import`; `python -m
  admin_ai_platform` boots in both modes; key public endpoints return.
- **Schema smoke:** `init_db()` on empty Postgres creates the IN tables; idempotent.
- **Runtime (`verify` + Claude_Preview):** demo page (gallery nav, live generatePage, form, voice) and
  `/admin` render clean; cross-origin embed (Shadow DOM, CORS, allowlist reject); local WP install.
- **Lint:** `ruff` on the package. **Security-review:** required on M7 (embed/CORS) + M8 (SSO) + webhooks.

## Execution milestones

| ID | Milestone | Depends on |
|----|-----------|------------|
| M0 | Scaffolding, shared infra (`db`/`llm`/`cost`/`config`/`create_app`), mode config, schema, scheduler | — |
| M1 | Visitor chat slice: chat+gallery+forms+media blueprints, modern widget (live render), voice, demo | M0 |
| M2 | Admin core: dashboard shell (IN tabs), admin_chat (+approval), provider, chat history | M0 |
| M3 | Cost + caps + digest; skills + MCP | M2 |
| M4 | RAG + automations + scraper (+ ticks) | M2 |
| M5 | Messaging (+webhooks/unsubscribe) + reviews (+/r/) + presentations | M3, M4 |
| M6 | Commerce + tenancy (embed-key/allowlist mgmt, snapshot, dev console, secrets) + VELO | M5 |
| M7 | Embed snippet + cross-origin widget + embed auth/CORS/rate-limit (security-review) | M1, M6 |
| M8 | WordPress plugin + SSO embedded admin (security-review) | M7, M2 |
| M9 | Docs (incl. deploy/admin decision matrix) + final verify (demo, cross-origin, WP) | M1–M8 |

## Process

Local-only git, branch-per-milestone (`task/NNN-...`), conventional commits, 6-point verification gate
before each merge to `main` (`git merge --no-ff`). M0+M1 land first as a runnable slice. The user's
pre-existing uncommitted changes (`scripts/*`, `.config/`, `.local/`) are NOT touched — only new
`admin_ai_platform/`, `embed/`, `wordpress-plugin/`, `tasks/`, `PLAN.md` files are staged.
