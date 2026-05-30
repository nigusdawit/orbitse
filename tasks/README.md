# Tasks — Admin/AI Platform Extraction

Master index. Detailed task files are fleshed out as each milestone is approached (downstream stubs
expand on first touch to avoid premature detail that drifts). See root `PLAN.md` for the overall plan.

| ID | Title | Status | Branch | Depends on | Parallel-with | Drift |
|----|-------|--------|--------|------------|---------------|-------|
| 000 | M0 — Scaffolding & shared infra | done | task/000-scaffolding-shared-infra | — | — | Module relocation deferred to consuming milestones |
| 001 | M1 — Visitor chat vertical slice | done | task/001-visitor-chat-slice | 000 | 002 | Gate GREEN vs embedded Postgres (19/19); live LLM+browser visuals still manual |
| 002 | M2 — Admin core | done | task/002-admin-core | 000 | 001 | Gate 47/47 vs embedded Postgres; admin chat LLM stream needs key (manual) |
| 003 | M3 — Cost + Skills/MCP | done | task/003-cost-skills-mcp | 002 | 004 | Gate 70/70 vs embedded Postgres; MCP/custom-skill live exec needs a server/key |
| 004 | M4 — RAG + Automations + Scraper | done | task/004-rag-automations-scraper | 002 | 003 | Gate 94/94 vs embedded Postgres (pgvector present); full embed/scrape-AI need a key |
| 005 | M5 — Messaging + Reviews + Presentations | done | task/005-messaging-reviews-presentations | 003,004 | — | Gate 116/116; live email/SMS send needs Resend/Twilio keys |
| 006 | M6 — Commerce + Tenancy + VELO | done | task/006-commerce-tenancy-velo | 005 | — | Gate 137/137; full Stripe Checkout + 30-cmd VELO are follow-ons (need keys) |
| 007 | M7 — Embed snippet + cross-origin widget | done | task/007-embed-widget | 001,006 | — | Gate 147/147; security-review found+fixed 2 cost-abuse holes |
| 008 | M8 — WordPress plugin + SSO | done | task/008-wordpress-plugin | 007,002 | — | Gate 159/159; security-review fixes applied; PHP unverified (no php in sandbox) |
| 009 | M9 — Docs + final verify | done | task/009-docs-verify | 001-008 | — | Final: 159/159 gate, ruff+unit+node clean, live 6/6 200 |

## Phase 2 — gap closure (see `PLAN_PHASE2.md`; DRAFT, awaiting approval)

| ID | Title | Status | Branch | Depends on |
|----|-------|--------|--------|------------|
| 010 | M10 — Scheduler ticks + multi-worker safety + backed rate limit | done | task/010-scheduler-and-scaling | — | Gate 175/175; Postgres-backed rate limiter + advisory-lock leader + all ticks registered; fixed weekly_dow=0 falsy bug |
| 011 | M11 — Stripe end-to-end (orders, bookings, webhook, sync) | done | task/011-stripe-end-to-end | 010 | Gate 205/205; verified-webhook idempotent routing + refund hardening (security-review: 3 fixed); live test-mode purchase → M21 |
| 012 | M12 — Events ticketing | done | task/012-events-ticketing | 011 | Gate 224/224; free/paid/donation RSVPs, capacity reservation (no double-sell), webhook confirm/free-seats, lookup_events. Landed on main directly (commit e4e24ad) |
| 013 | M13 — Full visitor lookup tools + dropped content + web search | done | task/013-visitor-lookup-parity | — | Gate 265/265; 12 new lookup tools + content CRUD + web-search (fail-closed); bookService UI chips → M16 |
| 014 | M14 — Integrations completion (voice admin, reviews agg, MCP OAuth, deck import, SMS) | done | task/014-integrations-completion | 010 | Gate 277/277; voice admin, reviews aggregation+AI-draft, MCP OAuth, pptx import+narration, SMS STOP/inbound. Live provider calls → M21 |
| 015 | M15 — Analytics (pageviews + dashboards) | done | task/015-analytics | — | Gate 289/289; pageview/duration tracking (deduped, UA parse), summary+chart+chat+forms dashboards, loader fires tracking |
| 016 | M16 — Admin dashboard SPA — all tabs | done | task/016-admin-dashboard-spa | 011-015 | Gate 304/304; all subsystem tabs (data-driven renderResource + bespoke), JS syntax-checked, dep-free. Browser per-tab pass → M21 |
| 017 | M17 — Onboarding (setup wizard + client checklist + AI assistant + agency provisioning) | done | task/017-onboarding | 016 | Gate 322/322; /setup provision+self-close, hashed admin pw override, checklist, seed tools, agency provision-tenant |
| 018 | M18 — Multi-tenant single-DB isolation + per-tenant admin users | deferred | task/018-multitenant-isolation | 010 | **Not needed under silo** (separate DB per client = free isolation). Revisit only if a pooled central-SaaS tier is added → use Postgres RLS, not hand-scoped queries |
| 019 | M19 — Security hardening (CSRF + secrets-at-rest) | done | task/019-security-hardening | — | Gate 339/339; CSRF (all /admin), Fernet secrets-at-rest, nonce'd CSP + headers. security-review: 4 fixed |
| 020 | M20 — Deploy artifacts + widget bundling + migrations + snapshot CLI | not_started | task/020-deploy-and-assets | — | Add: additive-only Alembic, per-instance widget, per-client secrets (silo provisioning) |
| 022 | M22 — Fleet sync (managed defaults + local override + rollout) | not_started | task/022-fleet-sync | 019,020 | Silo central-control: master pushes features; client config in their DB stays. Replaces M18's central-control role |
| 021 | M21 — Verification (browser + live-key E2E + CI) | not_started | task/021-real-env-verification | 011-020,022 |

**Status legend:** not_started | in_progress | paused | blocked | awaiting_review | done

**Concurrency note:** M1 and M2 touch disjoint files (visitor widget/chat vs admin shell) and can run
in parallel; M3 and M4 likewise. Everything depends on M0's shared infra landing first.
