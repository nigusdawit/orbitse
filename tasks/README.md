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
| 020 | M20 — Deploy artifacts + widget bundling + migrations + snapshot CLI | done | task/020-deploy-and-assets | — | Gate 352/352; package Dockerfile/compose/Railway/Render, hashed widget bundle, snapshot CLI, additive-only policy. Container boot → M21 |
| 022 | M22 — Fleet sync (managed defaults + local override + rollout) | done | task/022-fleet-sync | 019,020 | Gate 377/377; versioned-merge managed defaults, signed bundles (replay/TOCTOU-hardened), override-of-record, feature rollout. security-review: 4 fixed |
| 021 | M21 — Verification (browser + live-key E2E + CI) | done | task/021-real-env-verification | 011-020,022 | GitHub Actions CI + VERIFICATION.md runbook; gate 377/377, unit 71p, lint clean; browser/live-key/WP/Docker = operator runbook |

## Phase 3 — Replit re-import hardening (see `PLAN` in ~/.claude/plans/serialized-floating-boot.md)

| ID | Title | Status | Branch | Depends on | Parallel-with | Drift |
|----|-------|--------|--------|------------|---------------|-------|
| 023 | Harden monolith for clean Replit re-import (main.py + boot fixes) | done | task/023-replit-import-hardening | — | — | |
| 024 | Two-role admin (super-admin/client) — backend: roles, gating, registry | done | task/024-two-role-auth-backend | — | — | |
| 025 | Two-role admin — frontend: per-tab role+flag gating + verify | done | task/025-role-tab-gating-frontend | 024 | — | |

## Phase 4 — Admin AI hardening (pylego ports; see `PLAN_ADMIN_AI.md`)

| ID | Title | Status | Branch | Depends on | Parallel-with | Drift |
|----|-------|--------|--------|------------|---------------|-------|
| 026 | pylego foundation + Observability + Evals | done | task/026-pylego-observability-evals | — | — | |
| 027 | pylego Reliability (llm_router fallback/retry/timeout + rate limit) | done | task/027-pylego-reliability | 026 | — | |
| 028 | pylego Smarter context (token-trim + semantic response cache) | done | task/028-pylego-context | 027 | — | |
| 029 | pylego Safety (sqlguard + redact + structured args + action-queue) | done | task/029-pylego-safety | 028 | — | |

## Phase 5 — AI Control & Activity (panel-controlled + persisted; see `PLAN_AI_CONTROL.md`)

| ID | Title | Status | Branch | Depends on | Parallel-with | Drift |
|----|-------|--------|--------|------------|---------------|-------|
| 030 | AI Control settings backend (DB-backed live knobs + routes) | done | task/030-ai-control-settings | 026–029 | — | |
| 031 | AI Activity persistence (obs DB sink + /admin/api/ai-activity) | done | task/031-ai-activity | 030 | — | |
| 032 | History summarization (summarize dropped turns) | done | task/032-history-summarize | 030 | — | |
| 033 | AI Control + AI Activity admin tabs (super-admin-only) | done | task/033-ai-control-tabs | 030,031 | — | |

## Phase 6 — Visitor AI growth program (roadmap: ~/.claude/plans/serialized-floating-boot.md)

| ID | Title | Status | Branch | Depends on | Drift |
|----|-------|--------|--------|------------|-------|
| 034 | Epic A: visitor activity tracking (surface col + obs wiring) | done | task/034-visitor-activity | 031 | |
| 035 | Epic A: visitor reliability/context (pylego) + eval seed | done | task/035-visitor-pylego | 034 | |
| 036 | Epic B: RAG audience scoping + doc portal | done | task/036-rag-audience | 034 | |
| 037 | Safety: master AI-enhancements kill switch | done | task/037-master-killswitch | 030 | inserted ahead of roadmap (user-requested off-switch) |
| 038 | Epic B: visitor KB tool (audience-scoped retrieval) | done | task/038-visitor-kb-tool | 036 | |
| 039 | Epic B: async ingestion (gated, default inline) | done | task/039-rag-async | 038 | hybrid retrieval split to a follow-up |
| 039b | Epic B: optional OCR ingestion | not_started | task/039b-rag-ocr | 039 | |
| 040 | Epic C: per-request model routing | done | task/040-model-routing | 034 | Gate 8/8 model-routing tests + full migration chain clean; default-off identity, master-switch-inert, routes both admin+visitor to a fast model for short turns |
| 041 | Epic C: prompt caching + page-gen speed | done | task/041-prompt-cache | 040 | Gate 14/14 (7 prompt-cache + routing regression); Anthropic cache_control on system prompt at _stream_round_claude (covers admin+visitor+page-gen); default-off plain-string shape, master-switch-inert; OpenAI auto-caches |
| 042 | Epic D: visitor profile/CRM + needs capture | done | (on main) | 034 | Gate 13/13 + migration chain (0012) clean + 23 prior AI tests green; security-review: 2 fixed (bounded profiler concurrency, redact stored PII). Landed on main directly (commits e187ae4, 04b6ce7) |
| 043 | Epic D: newsletter subscribe + self-service portal | done | task/043-newsletter | 042 | Gate 13/13 + migration chain clean; subscribe_newsletter tool (gated, consent-safe, no silent re-opt-in) + public /preferences portal (scoped HMAC token, fail-closed on insecure secret). security-review: 1 fixed (MED) |
| 044 | Epic D: deals/offers + proactive engine | done | task/044-deals | 042 | Gate 9/9 + migration 0013 clean; offers table + gated lookup_offers tool (tag-targeted contextual surfacing) + super-admin CRUD. Drift: bespoke admin tab deferred (manageable via CRUD API now) |
| 045 | Epic D: agent tools (capture_lead/notify_team/request_callback) | done | task/045-growth-tools | 042 | Gate 13/13 + migration 0014 clean; 3 gated tools + leads/callbacks tables + super-admin read APIs. security-review: recipient-smuggling defense verified + 1 fixed (MED: outbound rate limit) |
| 046 | Epic E: visitor multi-agent intent router | done | task/046-visitor-personas | 045 | Gate 12/12 + migration 0015 clean; visitor_personas table + cheap classifier + apply (tool constraint + prompt suffix + model override) wired in api_chat, default-off single-agent; super-admin CRUD. Drift: bespoke admin tab deferred (CRUD API now) |
| 047 | Epic F: book_meeting via Calendar MCP | done | task/047-meetings | 045 | Gate 11/11 + migration 0017 clean; book_meeting tool + meetings table + gating + team notify; optional calendar-MCP push hook (live push = operator runbook, store-only without creds) |
| 048 | Epic F: request_callback + handoff summary | done | task/048-callback-handoff | 045 | Gate 7/7 + migration 0016 + 25 prior tests clean; ContextVar plumbs live chat to tools, _handoff_summary on request_callback (gated default-off), stored + in team notification. No creds needed (the no-creds part of Epic F) |
| 049 | Epic F: live AI phone call (Twilio Voice + media bridge) | done | task/049-live-call | 048 | Gate 10/10 + migration 0018 clean; Twilio Voice webhooks + voice_calls table + gating + TwiML (Stream→wss when configured). security-review: 1 fixed (HIGH: fail-closed without auth token). Live media bridge = operator runbook |
| 050 | Phase 6 admin dashboard tabs (Offers, Personas, Leads & CRM) | done | task/050-phase6-admin-tabs | 042-049 | Gate 2/2 (render markers + role gating); super-admin CRUD UI for offers/personas + read-only Leads & CRM multi-pane (leads/callbacks/meetings/voice/profiles). node --check clean, dep-free |
| 051 | Epic F activation (book_meeting ISO datetime + voice media bridge) | done | task/051-epicf-activation | 047,049 | Gate 13/13 meetings (+migration 0019) + 8/8 voice_bridge; book_meeting validates a model-supplied RFC3339 start before any calendar push (else store-only); provider-flexible voice_bridge/ (echo + openai realtime + slots), live server/call = operator runbook |
| 052 | Make public sections industry-agnostic (Task #9) | done | task/052-neutral-copy | — | Gate 8/8 + migration 0023 (neutralizes live rows still on old defaults) verified on injected old data; neutralized section nav, landing headers, chat persona (Marco/Concierge), system prompt, blog seed, quick prompts across app.py + index.html + script.js. Layout/schema untouched |

## Phase 7 — Datahub (AI-assisted data layer + dashboards; see ~/.claude/plans/serialized-floating-boot.md)

| ID | Title | Status | Branch | Depends on | Drift |
|----|-------|--------|--------|------------|-------|
| 053 | Semantic-layer schema + app-DB-as-connection + manual CRUD | done | task/053-datahub-semantic-layer | — | Gate 7/7 + migration 0024; db_table/column_annotations + relationships + examples (ai_generated/reviewed); connection 0 = app DB |
| 054 | Connection-aware introspection + read-only query + semantic context | done | (on main) | 053 | Gate 12/12 (real 2nd PG as external); security-review: 2 fixed (no DSN in errors, external secret-column redaction). admin_inspect_connection/admin_query_connection |
| 055 | AI auto-define (assistant drafts the semantic layer) | done | task/055-datahub-ai-define | 053,054 | Gate 6/6 (stubbed LLM); _dh_ai_define + admin_define_schema; samples redacted before LLM; reviewed rows preserved |
| 056 | Save SQL as a connection-aware skill (AI + manual) | done | task/056-datahub-save-query | 054 | Gate 7/7 + migration 0025 (custom_sql_skills.connection_id); admin_save_query creates DISABLED skill; external execution |
| 057 | In-chat chart rendering | done | task/057-datahub-inchart | 054 | Gate 6/6; render_chart tool + dedicated `chart` SSE event + admin-chat Chart.js renderer |
| 058 | AI builds persistent dashboards + save-chat-chart | done | task/058-datahub-dashboards | 057 | Gate 7/7; 'static' widget source + admin_create_dashboard + /datahub/save-chart + chat "Save to dashboard" button |
| 059 | Datahub tab UI | done | task/059-datahub-tab | 053-058 | Gate 3/3 + 48/48 combined; super-admin tab: connections + schema browser w/ inline annotation edit + "AI-suggested · review" badges + "✨ Auto-define" + examples + assistant hand-off |
| 060 | Datahub follow-ups: is_sensitive toggle + live-verify | done | task/060-datahub-followups | 059 | Column-editor sensitive checkbox (persists); live browser pass of the tab; also fixed Connect-a-database (prompt→modal) |
| 061 | Multi-DB connectors (MySQL + "Any database URL") | done | task/061-multidb-connectors | 059 | Gate 8/8 (+47 combined); Postgres keeps psycopg2, MySQL+generic via SQLAlchemy (pymysql); kind-aware run/introspect dispatch for datahub + dashboard widgets; connections shared across both surfaces; modal kind dropdown. Live MySQL = operator step |

## Phase 8 — Research & Content Engine (refactor the weak scraper into deep research + a content studio; all super-admin-gated, default-off, additive)

| ID | Title | Status | Branch | Depends on | Drift |
|----|-------|--------|--------|------------|-------|
| 062 | Foundation: Sources/reports/drafts/capabilities schema + knobs + read APIs | done | task/062-research-content-foundation | — | Gate 6/6 + migration 0026; 4 tables; AI Control group "Research & Content" (8 knobs, all default-off + master-switch); read APIs for reports(+sources) & drafts |
| 063 | Gather: multi-source fetch into the Sources layer | done | task/063-research-gather | 062 | Gate 8/8; reuses scraper SSRF-guarded fetch + render fallback; content-hash dedup; rate-limited; gather_sources tool + POST /admin/api/research/gather; gated by research_hub_enabled |
| 064 | Deep Research: fan-out → fetch → cited synthesis | done | task/064-deep-research | 063 | Gate 14/14 (+22 with 063); plan→discover(web search)→fetch(063 gather)→synthesize; anti-hallucination citation filter (drops unfetched URLs); cost-capped (max_sources≤25, 4 sub-q / 3 searches); OpenAI JSON mode, stub-tested; run_research tool + POST /admin/api/research/run |
| 065 | Content Studio (text): one report → many drafts, review-gated | done | task/065-content-studio-text | 062 | Gate 10/10 (+38 Phase 8); configurable RCE_CONTENT_TYPES (blog/social/linkedin/newsletter/email/faq/summary + custom fallback); report→drafts (status='draft', review-gated); content_model knob; generate_content tool + routes (types/generate/get-one/review-update); gated by content_studio_enabled |
| 066 | Visual content scaffold: image/diagram/clip gen + stitch + embed | done | task/066-visual-content | 065 | Gate 14/14 (+52 Phase 8); content_assets table (migration 0027); pluggable RCE_VISUAL_PROVIDERS (placeholder no-spend default + opt-in openai_image); diagram=Mermaid(ready), clip=storyboard(planned scaffold), stitch=planned clip; embed into draft body; generate_visual tool + routes; gated by visual_content_enabled |
| 067 | Publish capabilities registry + auto-post (mcp/webhook/http_api/python) | done | task/067-publish-capabilities | 062 | Gate 17/17 (+69 Phase 8); publish_log (migration 0028); CRUD w/ Fernet-encrypted+redacted config; SSRF-guarded send (run-time re-validate + DNS pin); python double-gated (operator command list + RCE_PYTHON_CAPABILITY_ENABLED env, shell=False); autopublish_enabled gate; audit log. Security-review: 1 HIGH fixed (client-role could reach AI tools → added _rce_tool_role_guard to all 5 Phase-8 tools) |
| 068 | Automation links: triggers → research/generate/publish actions | done | task/068-automation-links | 064,065,067 | Gate 9/9; additive automations.register_action seam; 3 actions (rce_research/rce_generate_content/rce_publish) chainable via merge tags ({{step1.report_id}}); gates propagate as clean step failure; existing automations untouched |
| 069 | Research Hub + Content Studio tabs (UI) | not_started | task/069-rce-tabs | 064,065 | |

**Status legend:** not_started | in_progress | paused | blocked | awaiting_review | done

**Concurrency note:** M1 and M2 touch disjoint files (visitor widget/chat vs admin shell) and can run
in parallel; M3 and M4 likewise. Everything depends on M0's shared infra landing first.
