# PLAN — Phase 2: close every gap in `admin_ai_platform`

- **Status:** APPROVED (2026-05-29) — M10–M17 DONE; deployment-model decision below
- **Drafted:** 2026-05-29
- **Builds on:** `PLAN.md` (Phase 1, M0–M9 COMPLETE)
- **Task index:** `tasks/README.md` (rows 010–022)

## Deployment-model decision (2026-05-29) — SILO

The operator chose the **silo** model: one app instance + one database per
client (`DEPLOY_MODE=self_host`, `tenant_id=1`). Consequences:

- **M18 (single-DB row isolation / RLS) → DEFERRED, not needed.** Separate
  databases give free, airtight isolation. Revisit only if a pooled central-SaaS
  tier is later added (then use Postgres **RLS**, not hand-scoped queries).
- **Central control becomes a fleet problem, not an isolation problem.** New
  milestone **M22 — fleet sync**: master pushes code/UI (image rollout), schema
  (additive Alembic per-instance), and **managed default data** over the VELO
  channel, while each client's customizations live in their DB and are never
  clobbered (managed-vs-`is_overridden` layer; `tenant_features` gradual rollout;
  per-instance migration/version status).
- **Load-bearing rule:** all per-client behavior is DB data; code is identical
  everywhere — so an image update can never erase a client's config.
- **Remaining order:** M19 (security hardening) → M20 (deploy artifacts, incl.
  additive-only Alembic + per-instance widget + per-client secrets) → M22
  (fleet sync) → M21 (final verification).

## Goal

Take the extracted `admin_ai_platform` from "core complete, several follow-ons"
to **production-shippable with no known gaps**: every subsystem fully wired and
verified, full Stripe + events commerce, all visitor lookup tools, complete
admin UI, onboarding for operator/client/agency, real multi-tenant isolation,
security hardening, deploy artifacts, and real-environment (browser + live-key)
verification.

## Non-goals

- Re-touching the original `app.py` / public marketing site (still frozen).
- New product features beyond reaching parity + production-readiness.

## The full gap inventory (what Phase 2 closes)

**Wiring / runtime**
- G1 Background scheduler ticks unregistered (weekly cost digest, scrape
  schedules, review collector + auto-ask, RAG reindex, messaging campaign
  dispatch). Only automations ticks fire today.
- G2 Multi-worker scheduler safety (only one worker should run ticks → DB
  advisory lock) + ProxyFix/trusted-proxy hops for correct client IP.
- G3 Rate limiter is in-process → Postgres/Redis-backed for multi-worker.

**Commerce**
- G4 Stripe Checkout end-to-end: product orders (payment intent / checkout
  session) + service deposit/full bookings → redirect.
- G5 Stripe webhook: signature verify + idempotent `checkout.session.completed/
  expired` routing (orders + bookings → paid, FOR UPDATE) + product sync
  (`stripe_sync`/`stripe_settings` relocate).
- G6 Booking completeness: contract-upload flow (`/booking/<token>/contract`),
  booking partial-save + Forms-mirror managed form, confirmation emails.
- G7 Orders admin: detail, status, refund, customers.
- G8 **Events ticketing** (entirely absent): `events` + `event_rsvps`, free/paid/
  donation modes, capacity reservation, public RSVP + Stripe, admin CRUD.

**Visitor AI parity**
- G9 Remaining lookup tools + their data tables/CRUD: services, products,
  events, blog, team, faq, testimonials, experiences, pricing, business_info,
  custom_section_items, service_availability. (Today only gallery/forms/
  generated_page/presentation/KB exist.)
- G10 `lookup_web_search` (Brave + Anthropic fallback) + web-search policy.

**Integrations completion**
- G11 Voice admin: settings PUT, intros CRUD + audio generation, voice sample/
  preview, ElevenLabs voice list, legacy `/api/voice/tts` pre-gen.
- G12 Reviews aggregation: real Google Places / Yelp / TripAdvisor fetch in
  `refresh_destination` + nightly snapshot tick + AI review-ask drafting/send.
- G13 MCP OAuth flow (oauth start / callback / disconnect) beyond bearer/header.
- G14 Presentations import (Office/PPTX → per-slide images via LibreOffice) +
  AI narration generation.
- G15 Messaging completeness: campaign `send_at` scheduling tick, SMS STOP
  opt-out + inbound-SMS webhook → AI agent.
- G16 Analytics (absent): `page_views` tracking endpoints + admin dashboard
  (UTM/device/referrer/sessions) + chat/form analytics views.

**Admin UI**
- G17 Dashboard SPA tabs for ALL subsystems (cost, skills, MCP, RAG/KB,
  automations, scraper, messaging, reviews, presentations, commerce, events,
  analytics, tenancy/embed-keys, secrets, dev console). Today only M2 tabs are rich.

**Onboarding**
- G18 First-run `/setup` wizard (preset, paste keys, business name, create admin
  + first embed key) — operator self-serve.
- G19 Client onboarding checklist + an AI onboarding assistant (guided "connect
  X / add content / try it") inside admin.
- G20 Agency provisioning UI (create tenant + clone snapshot + issue embed/SSO
  keys) wrapping the existing snapshot + VELO `bootstrap_install`.

**Multi-tenant & security**
- G21 Single-DB multi-tenant isolation: `tenant_id` columns on content/runtime
  tables + scope every query by `current_tenant_id()`; per-tenant admin users +
  login; central-mode session→tenant resolution. (Decision gate: keep one-DB-
  per-tenant vs. enable single-DB — plan implements single-DB isolation.)
- G22 CSRF protection on state-changing admin routes (prereq for `SameSite=None`
  cross-site WP embed).
- G23 Secrets at rest: Fernet-encrypt MCP `auth_credential`, automation webhook
  secrets, review/provider keys; relocate `env_manager` secrets UI.

**Deploy & assets**
- G24 Deploy artifacts: package `Dockerfile`, `docker-compose.yml`,
  `pyproject`/`requirements`, gunicorn entry, `.env.example`, Render/Fly recipes.
- G25 Widget asset bundling (concat/minify chat-ui+voice), versioned URLs +
  cache headers; `WIDGET_CDN_BASE` support.
- G26 Migration strategy for prod upgrades (Alembic alongside `schema.py`, or a
  documented additive-only policy) + snapshot/clone completeness (more tables,
  admin-config + secret redaction) + a `snapshot.py` CLI.

**Verification**
- G27 Real-browser E2E (Preview/Playwright): demo widget (gallery nav, live
  generatePage, form fill, voice), `/admin`, a cross-origin embed page, and a
  local WordPress install (PHP `php -l` + activate + SSO iframe).
- G28 Live-key E2E smoke: a real `/api/chat` round, voice TTS/STT, RAG ingest+
  retrieve, a Stripe test-mode purchase, an email/SMS send — scripted + documented.
- G29 Test + CI expansion: per-blueprint route tests, the embedded-PG gate in CI,
  ruff/typecheck, PHP lint.

## Execution milestones (→ tasks 010–021)

| ID | Milestone | Closes | Depends |
|----|-----------|--------|---------|
| M10 | Scheduler ticks + multi-worker safety + backed rate limit | G1,G2,G3 | — |
| M11 | Stripe end-to-end (orders, bookings, webhook, sync) | G4,G5,G6,G7 | M10 |
| M12 | Events ticketing | G8 | M11 |
| M13 | Full visitor lookup tools + dropped-content data/CRUD + web search | G9,G10 | — |
| M14 | Integrations completion (voice admin, reviews agg, MCP OAuth, deck import, messaging, SMS) | G11,G12,G13,G14,G15 | M10 |
| M15 | Analytics (pageviews + dashboards) | G16 | — |
| M16 | Admin dashboard SPA — all tabs | G17 | M11–M15 |
| M17 | Onboarding: /setup wizard + client checklist + AI assistant + agency provisioning | G18,G19,G20 | M16 |
| M18 | Multi-tenant single-DB isolation + per-tenant admin users | G21 | M10 |
| M19 | Security hardening: CSRF + secrets-at-rest encryption | G22,G23 | M18 |
| M20 | Deploy artifacts + widget bundling + migrations + snapshot CLI | G24,G25,G26 | — |
| M21 | Verification: browser + live-key E2E + CI | G27,G28,G29 | M11–M20 |

## Testing strategy

Every milestone keeps the existing bar: extend `_gate_runner.py` with new
DB-backed checks, `ruff` + `pytest` + `node --check` clean, `security-review`
(agent) on anything touching auth/secrets/payments/webhooks/CSRF. Stripe uses
test-mode keys; live-key + browser + WordPress checks are the M21 real-env pass.
Each milestone: branch `task/0NN-*`, gate-before-merge, `--no-ff`.

## Decisions (confirmed 2026-05-29)

1. **Multi-tenant (M18):** implement **single-DB row isolation** (tenant_id
   everywhere + query scoping + per-tenant admin users).
2. **Stripe (M11):** **one-time payments only** (Checkout) — no subscriptions.
3. **Deploy (M20):** ship recipes for **Docker/compose + Railway + Render**.
4. **Onboarding assistant (M17):** reuse the admin AI with an onboarding system
   prompt + a checklist UI.
5. **Order:** build straight through **M10 → M21**, gated + merged per milestone.
