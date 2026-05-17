# Skills Catalog — Index

Every reusable feature pattern extracted from this template, grouped by category. Each link opens a self-contained skill blueprint (When to use / Architecture / Data model / API surface / Key files / External deps / Pitfalls / Adaptation notes / Adoption checklist).

See [`README.md`](./README.md) for how to use the catalog.

---

## Admin Tooling
- [Snapshot & Revert for Settings](./admin-tooling/01-snapshot-and-revert.md) — JSON snapshots of every admin save with one-click revert.
- [Developer Console](./admin-tooling/02-dev-console.md) — in-browser provider health probes (OpenAI, Twilio, Stripe, etc.).
- [Preflight Env / Health Checks](./admin-tooling/03-preflight-checks.md) — surface missing env vars and broken integrations on deploy.
- [Per-Conversation Skills Toggle](./admin-tooling/04-per-conversation-skills-toggle.md) — disable individual AI tools per chat session.
- [Edit-and-Rerun Chat Branch](./admin-tooling/05-edit-and-rerun-chat-branch.md) — ChatGPT-style branch from an edited user message.
- [Markdown / JSON Chat Export](./admin-tooling/06-markdown-json-chat-export.md) — one-click export of any AI conversation.

## AI Pipelines
- [Streaming Tool-Call Loop](./ai-pipelines/01-streaming-tool-call-loop.md) — server-streamed chat that also dispatches tool calls.
- [Partial-JSON Streaming Decoder](./ai-pipelines/02-partial-json-streaming-decoder.md) — render structured AI actions while tokens stream.
- [Live Editable System Prompts](./ai-pipelines/03-live-editable-system-prompts.md) — non-developers tune AI behavior from the admin UI.
- [Semantic Response Cache](./ai-pipelines/04-semantic-response-cache.md) — embedding-based dedup of near-duplicate chat questions.
- [Human-in-the-Loop Approvals](./ai-pipelines/05-human-in-the-loop-approvals.md) — gate write/destructive tool calls behind admin approval.
- [Persona Router](./ai-pipelines/06-persona-router.md) — route one chat endpoint across many task-specific agent personas.
- [Parallel Subagents (`spawn_agents`)](./ai-pipelines/07-parallel-subagents.md) — fan a request out to 2–5 independent subtasks.
- [Multi-Modal Chat Attachments](./ai-pipelines/08-multimodal-chat-attachments.md) — accept image + document attachments in chat.
- [Live Progressive Iframe Render](./ai-pipelines/09-live-progressive-iframe-render.md) — render `generatePage` HTML chunks as they stream.

## Analytics
- [First-Party Page-View Tracker](./analytics/01-first-party-page-view-tracker.md) — UTM + session tracking without external SDKs.
- [Device / Browser / OS / Referrer Breakdown](./analytics/02-device-browser-os-breakdown.md) — UA parsing for submissions and views.
- [Chart.js Admin Dashboards](./analytics/03-chartjs-admin-dashboards.md) — line/stacked-bar/donut charts inside the admin tabs.

## Auth & Multi-Tenancy
- [Fernet Secret Encryption at Rest](./auth/01-fernet-secret-encryption.md) — encrypt admin-pasted credentials in the DB.
- [Multi-Tenant Scaffolding](./auth/02-multi-tenant-scaffolding.md) — single-tenant today, plural-ready table layout.
- [Password-Protected Admin Gate](./auth/03-admin-gate.md) — single-operator login with session cookies.
- [Super-Admin Lock + Audit Log](./auth/04-super-admin-audit.md) — second-factor gate on destructive admin actions.
- [Replit OAuth Bridge](./auth/05-replit-oauth-bridge.md) — "Log in with Replit" identity for visitors.

## Booking & Reservations
- [Weekly Availability Engine](./booking/01-weekly-availability-engine.md) — recurring rules ∪ per-date overrides minus bookings.
- [Service Add-On Snapshot](./booking/02-service-addon-snapshot.md) — freeze add-on prices at booking time.
- [Offline Contract Upload](./booking/03-offline-contract-upload.md) — tokenized public page for signed-PDF return.
- [Service Bookings ↔ Forms Mirror](./booking/04-service-booking-forms-mirror.md) — managed system form that's mutation-locked.
- [Tri-Mode Event RSVPs](./booking/05-tri-mode-event-rsvps.md) — free / paid / pay-what-you-wish in one flow.
- [Capacity Reservation Pre-Checkout](./booking/06-capacity-reservation-pre-checkout.md) — hold seats during the Stripe round-trip.

## Caching
- [Public-API Cache Headers](./caching/04-public-api-cache-headers.md) — allowlist + 6 defense layers for safe CDN caching.
- [Buffer-While-Streaming TTS Cache](./caching/05-tee-to-cache-streaming.md) — pay-once, stream-always with atomic tee-to-disk.

## Content & Site Builder
- [Page Section Registry](./content/01-page-section-registry.md) — drag-reorder + visibility toggle for landing sections.
- [Custom Section Templates](./content/02-custom-section-templates.md) — admin-authored sections from layout + data-showcase templates.
- [Drag-and-Drop Reordering](./content/03-drag-and-drop-reordering.md) — universal `sort_order` pattern across every list.
- [AI-Generated Saved Pages](./content/04-ai-generated-saved-pages.md) — persistable library of AI page generations.
- [Immersive Fullscreen Gallery](./content/05-immersive-fullscreen-gallery.md) — swipe / wheel / keyboard navigation.
- [Snap-Scroll Landing Template](./content/06-snap-scroll-landing.md) — CSS scroll-snap + IntersectionObserver fades.
- [Glassmorphic Design System](./content/07-glassmorphic-design-system.md) — backdrop-filter tokens + named surface presets.
- [Theme / Color Editor](./content/08-theme-color-editor.md) — live CSS-variable swapping from admin.
- [Loading Screen](./content/09-loading-screen.md) — theme-tinted glass overlay with shimmer + fade.

## Custom AI Skills
- [Custom SQL Skills](./custom-skills/07-custom-sql-skills.md) — admin-authored read-only SELECTs become AI tools.
- [Custom Webhook Skills](./custom-skills/08-custom-webhook-skills.md) — admin-authored HTTP tools with SSRF guards.
- [Unified Skill Catalog & Per-Chat Toggles](./custom-skills/09-skill-catalog-and-per-chat-toggles.md) — one registry for built-in, SQL, webhook, and MCP tools.

## Forms
- [Dynamic Form Builder](./forms/01-dynamic-form-builder.md) — admin-authored forms with multi-step + drag-reorder.
- [Partial / Abandon Capture](./forms/02-partial-abandon-capture.md) — auto-save half-filled forms; promote on completion.
- [Managed System Forms](./forms/03-managed-system-forms.md) — auto-generated, mutation-locked forms for built-in features.
- [UTM + Device + Referrer Metadata Pipeline](./forms/04-utm-device-metadata-pipeline.md) — attribution context on every submission.

## Integrations
- [OpenAI: Direct + Replit Proxy Split](./integrations/06-openai-direct-and-replit-proxy-split.md) — two clients routed by endpoint capability.
- [Anthropic Provider](./integrations/07-anthropic-provider.md) — Claude alongside OpenAI, per-agent choice.
- [MCP Remote Tool Bridge](./integrations/08-mcp-remote-tool-bridge.md) — runtime-wired remote tools (CRMs, Linear, GitHub, etc.).
- [Brave Search Tool](./integrations/09-brave-search-tool.md) — web search as an AI function-call tool.
- [Velo Agent Bridge](./integrations/10-velo-agent-bridge.md) — bridge chat to an external Velo agent.
- [Env Manager + Secrets UI](./integrations/11-env-manager-and-secrets-ui.md) — admin-side editor with status badges.

## Media
- [Pluggable Storage Layer](./media/05-pluggable-storage-layer.md) — one interface for local disk / S3 / object stores.
- [Image Optimizer (WebP Variants)](./media/06-image-optimizer-webp-variants.md) — automatic responsive WebP siblings.
- [Atomic File Write (`.part` + `os.replace`)](./media/07-atomic-file-write.md) — never serve a half-written file.
- [Asset Bundle Pipeline](./media/08-asset-bundle-pipeline.md) — pure-Python JS bundling without a build step.
- [Hashed Audio / TTS Disk Cache](./media/09-hashed-audio-tts-cache.md) — content-hash addressed cache for paid media.

## Messaging
- [Unified Send Helper (Email + SMS)](./messaging/01-unified-send-helper.md) — one entrypoint, one audit log row, two channels.
- [Merge-Tag Templates](./messaging/02-merge-tag-templates.md) — `{{first_name}}` personalization without a template engine.
- [Campaign Manager](./messaging/03-campaign-manager.md) — bulk email + SMS with scheduler and opt-out enforcement.
- [Tokenized Short Links (`/r/<token>`)](./messaging/04-tokenized-short-links.md) — per-recipient click + convert tracking.
- [STOP-Keyword SMS Opt-Out](./messaging/05-stop-keyword-optout.md) — TCPA/GDPR-compliant inbound-SMS handling.

## Payments
- [Stripe Checkout Dispatcher](./payments/01-stripe-checkout-dispatcher.md) — one route, many pay-for-this surfaces.
- [Idempotent Stripe Webhook Router](./payments/02-idempotent-stripe-webhook.md) — routes by `metadata.kind`, safe to replay.
- [Stripe Product / Price Sync](./payments/03-stripe-product-price-sync.md) — one-way local → Stripe price mirror.
- [Three-Tier AI Cost Caps](./payments/04-three-tier-cost-caps.md) — `alert_only` / `throttle` / `strict_block` per tenant.
- [Unit-Price Ledger](./payments/05-unit-price-ledger.md) — stamp the unit price at write time so history can't drift.
- [Weekly Cost Digest](./payments/06-weekly-cost-digest.md) — claim-then-send idempotency for Monday emails.
- [SMS-Segment Re-Pricing](./payments/07-sms-segment-repricing.md) — webhook patches quantity, never unit price.

## Presentations
- [AI Presentation Generator](./presentations/10-ai-presentation-generator.md) — narrated slide decks with per-slide TTS.
- [Unified Media Library + WebP Variants](./presentations/11-live-image-generation-pipeline.md) — the upload/serve substrate for all media features.

## RAG & Voice
- [Pgvector Cosine Search](./rag-voice/01-pgvector-cosine-search.md) — semantic search over chunked documents.
- [Document Ingest + Token-Aware Chunker](./rag-voice/02-document-ingest-and-chunker.md) — PDF/DOCX/PPTX/CSV → embeddings.
- [Knowledge Base Manager UI](./rag-voice/03-kb-manager-ui.md) — upload · status · reindex · citation viewer.
- [Auto-Extracted Long-Term Memories](./rag-voice/04-auto-memory.md) — ChatGPT-style "the assistant remembers" loop.
- [Cross-Chat Semantic Recall](./rag-voice/05-cross-chat-recall.md) — "as we discussed two weeks ago…" lookups.
- [Streaming Sentence-by-Sentence TTS](./rag-voice/06-streaming-sentence-tts.md) — speak each finished sentence in parallel with token stream.
- [Dual-Provider TTS (OpenAI + ElevenLabs)](./rag-voice/07-dual-provider-tts.md) — cheap default + premium upgrade path.
- [Hold-to-Record Voice Input](./rag-voice/08-hold-to-record-voice-input.md) — Web Speech ↔ Whisper switcher.
- [UTM-Targeted Welcome Voice Intros](./rag-voice/09-utm-voice-intros.md) — campaign-personalized greeting MP3s.
- [Per-IP Voice Daily Char Cap](./rag-voice/10-per-ip-voice-cap.md) — abuse cap that protects paid voice spend.

## Reviews
- [AI Review-Ask Drafter](./reviews/05-ai-review-ask-drafter.md) — LLM personalizes inside an admin-curated template envelope.
- [Aggregate Reviews Snapshot](./reviews/06-aggregate-reviews-snapshot.md) — Google / Yelp / TripAdvisor nightly cache.
- [Tokenized Review Short-Link](./reviews/07-tokenized-review-short-link.md) — click + convert tracking for each ask.

## Scheduler
- [In-Process Tick Scheduler](./scheduler/01-in-process-tick-scheduler.md) — recurring background work without Celery/Redis.
- [IFTTT Automation Engine](./scheduler/02-ifttt-automation-engine.md) — admin-wired "when X, do Y" rules.
- [Once-Per-Period Idempotency](./scheduler/03-once-per-period-idempotency.md) — claim-before-you-act for cross-tick safety.

## Scraping
- [URL + Objective Dual-Mode Scraper](./scraping/01-url-objective-scraper.md) — server-side fetch OR `web_search_preview` objective.
- [Rendered-Fetch Fallback](./scraping/02-rendered-fetch-fallback.md) — headless browser via ScrapingBee / Browserless for SPAs.
- [Recurring Scrape Scheduler](./scraping/03-recurring-scrape-scheduler.md) — hourly/daily/weekly scrapes with change-only notify.
- [Auto-Pause on Failures](./scraping/04-auto-pause-on-failures.md) — pause runaway jobs after N consecutive failures.

## SEO
- [Auto sitemap.xml + robots.txt](./seo/01-auto-sitemap-robots.md) — generated live from DB so new URLs index fast.
- [JSON-LD Structured Data](./seo/02-jsonld-structured-data.md) — inline rich-result eligibility from the same DB.
- [Per-Section SEO Overrides](./seo/03-per-section-seo-overrides.md) — deep-link `<title>` + meta on a single-page site.
- [AI Meta-Tag Suggester](./seo/04-ai-meta-tag-suggester.md) — "Ask AI" button for title/description/keywords.

## Visualization
- [Three.js Sphere View](./visualization/01-threejs-sphere-view.md) — section-carousel + classic image sphere modes.
- [Side-Panel & Split-Screen Chat](./visualization/02-side-panel-and-split-screen-chat.md) — chat companion panel during full-screen takeovers.
- [DOMPurify-Sanitized AI HTML](./visualization/03-dompurify-html-sanitization.md) — trusted gate before injecting model output.
- [Chat Markdown Rendering](./visualization/04-chat-markdown-rendering.md) — headings, lists, code, tables in chat bubbles.
- [Reading Progress Bar](./visualization/05-reading-progress-bar.md) — accent-colored scroll indicator for long-form pages.
- [Auto-Canvas Fallback](./visualization/06-auto-canvas-fallback.md) — promote long AI text into a fullscreen frosted canvas.
