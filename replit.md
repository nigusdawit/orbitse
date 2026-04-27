# Database-Driven Website Template

> **AI agents:** read [`AGENT_KNOWLEDGE_BASE.md`](./AGENT_KNOWLEDGE_BASE.md) first — it is the canonical agent-oriented map of this project (architecture, routes, tables, env vars, conventions). Use this `replit.md` for the long-form feature changelog detail.

## Overview

A database-driven website template built as a reusable, industry-agnostic HTML/CSS/JS application. All content (gallery slides, experiences, pricing, site settings, chatbot) is managed through a PostgreSQL database and a password-protected admin dashboard — no code editing needed to change content. Suitable for any business type: hospitality, real estate, restaurants, portfolios, agencies, and more.

The site features:
- **Snap-scroll landing page** with hero, highlights, experiences, pricing, testimonials, team, FAQ, blog, and business info/contact sections
- **Immersive fullscreen gallery** with swipe/wheel/keyboard navigation
- **AI chatbot with site control** — enable/disable from admin, supports built-in chat or external embed
- **Side-panel AI chat** — frosted glass panel slides in from the right when AI navigates gallery slides; shows only the agent's latest message by default with a toggle to reveal full conversation history; on mobile, appears as a compact bottom strip that expands when history is opened
- **Split-screen AI display** — for custom slides (showSlide, generatePage), a full overlay with chat + content is used
- **Immersive Sphere View** — fullscreen 3D experience with two modes: **Section Carousel** (default) shows site sections as glassmorphic HTML cards orbiting in 3D via CSS3DRenderer with WebGL particles; **Classic Sphere** shows rotating image sphere with particles. Both support scroll-to-zoom and drag-to-rotate. Admin-configurable (view mode, heading, particle count, rotation speed, card scale/gap, image source); uses Three.js + CSS3DRenderer
- **Proactive AI Voice Agent** — three independent toggleable features with multi-provider support: (1) UTM-targeted **welcome voice intros** (pre-generated MP3s cached on disk, matched against utm_source/medium/campaign/referrer with priority tie-break); (2) **visitor voice input** via browser-native Web Speech API (free) OR premium **OpenAI Whisper STT** (server-side, more accurate for non-English/noisy audio); (3) **AI voice replies** via standard **OpenAI TTS** (six voices, fast, low cost) OR premium **ElevenLabs TTS** (ultra-realistic, dynamic voice list from the customer's account). AI voice replies use **streaming TTS** so the visitor hears the first words within ~0.7-1.6s instead of waiting 3-5s for the full clip — the browser does a POST `/api/voice/tts/stream/prepare` (returns either a cache URL on a hit, or a one-shot tokenized GET URL on a miss), then the `<audio>` element fetches from `/api/voice/tts/stream/consume?token=...` which pipes provider bytes straight to the client while teeing them to the cache file via a unique-per-request `.part` (atomic `os.replace` on success, removed on disconnect/error). On top of that, AI replies are **spoken sentence-by-sentence in parallel with the chat stream** — `chatSendStreaming` calls `VoiceAgent.streamSpeakBegin/Feed/End/Cancel` so each completed sentence (detected via `.!?` + whitespace, with abbreviation guards for Mr./Dr./e.g./etc.) fires its own `/prepare` immediately and a sequential audio queue plays them in reading order. The visitor typically hears the first sentence ~1s after the AI emits its first period — well before the full response has finished generating. Bubbles are tagged `__voiceStreamSpoken=true` so the legacy whole-message hook (`chat:agent-message` listener) doesn't double-speak the same text. The legacy POST `/api/voice/tts` endpoint is kept for admin pre-generation. All audio is cached by `(provider, voice, model, text)` content hash so repeat plays are free; per-IP daily char cap of 30k prevents abuse. Premium providers gated by master `premium_enabled` toggle so trials/billing tiers can be flipped instantly. Admin "Voice Agent" tab includes voice preview buttons (▶ Listen) for both providers, dynamic ElevenLabs voice list with refresh, status badges showing which API keys are set, and per-provider usage logging (`tts_generate_openai` vs `tts_generate_elevenlabs` vs `stt_whisper`) for accurate billing breakdowns. Tables: `voice_settings` (singleton with v2 multi-provider columns), `voice_intros`, `voice_usage_log`. Requires `OPENAI_API_KEY` (direct, since the Replit AI proxy doesn't support `/audio/speech` or `/audio/transcriptions`) and optionally `ELEVENLABS_API_KEY`. Frontend logic in standalone `public/voice.js` with Web Speech ↔ MediaRecorder dispatch based on configured STT provider
- **Admin dashboard** at `/admin` (password-protected) for editing all content via a web interface
- **Database-driven content** — changes in admin are instantly visible on the public site
- **AI System Prompt Editor** — edit the AI's system prompt from admin without touching code
- **AI Live Site View (compact index + on-demand lookups)** — every chat message injects only a compact SITE INDEX (per category, just names + slugs of every gallery card, service, experience, pricing tier, product, event, blog post, team member, FAQ, etc.) plus brand identity, theme tokens, full forms schema (required-field tracking depends on it), the full landing page layout (every section in display order with enabled/DISABLED status + scrollToSection target IDs), the page library of saved AI-generated pages, and a TOOL USAGE block. The bulky descriptions/details/body text are **NOT** stuffed into the prompt — they live behind 14 OpenAI function-calling tools (`lookup_gallery_cards`, `lookup_services`, `lookup_experiences`, `lookup_pricing`, `lookup_products`, `lookup_events`, `lookup_blog`, `lookup_team`, `lookup_faq`, `lookup_testimonials`, `lookup_business_info`, `lookup_custom_section_items`, `lookup_generated_page`, `lookup_web_search`) that the AI calls on demand with narrow filters (slug, category, free-text query, limit). The streaming chat completion runs in a tool-call loop (capped at 4 rounds): per round it accumulates visible reply tokens AND tool_call deltas, executes any requested lookups server-side, appends the assistant+tool messages, and re-streams. Each lookup invocation is logged (name, args, row count, duration) into the new `chat_messages.tool_calls_json` JSONB column and surfaced in the admin Chat History view beside the AI message — so the admin can see exactly which slices of the site the AI pulled in to answer any turn. This makes per-turn token cost roughly constant regardless of how big the site grows.
- **Image Upload System** — upload images directly from admin, stored in `/uploads/`
- **Drag-and-Drop Reordering** — reorder gallery cards, experiences, pricing, testimonials, team, and FAQ by dragging rows
- **Toggleable Sections** — enable/disable Testimonials, Team, FAQ, and Footer from admin
- **Business Info & Social Links** — manage contact details, hours, and social media profiles from admin; dedicated landing page section with contact info cards and embedded Contact Us form
- **Contact Us Form** — database-driven contact form (slug: `contact-us`) with name, email, subject, message fields; submissions appear in admin Forms tab; also available as AI chatbot form collection
- **Testimonials/Reviews** — client quotes with star ratings, reviewer names/roles
- **AI Review Collector** — admin Reviews tab (Destinations / Requests / Insights) for managing post-purchase review-ask emails and SMS. Each ask carries a unique `/r/<token>` short link that records `clicked_at` on click and `converted_at` when an internal review form is submitted with `?r=<token>`. The AI (gpt-4o-mini) drafts a short personalized message using the recipient's name and what they bought/booked; the message is then wrapped in an admin-selected messaging template so brand/tone stays consistent. Triggers: manual buttons on order details and form-submission details, plus a scheduler sweep that auto-queues asks N days after `orders.status='paid'` or `event_rsvps.payment_status='paid'`. A nightly snapshot tick caches aggregate ratings (count + avg) per destination via Google Places, Yelp Fusion, and TripAdvisor Content APIs (controlled by `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY`) — destinations the admin marks `public_visible` are exposed via `/api/review-snapshots` for the public site.
- **Team/About** — team member cards with photo, name, title, bio
- **FAQ** — collapsible question/answer pairs
- **Page Layout Manager** — drag-to-reorder all site sections from admin, toggle sections on/off
- **Custom Section Builder** — create new sections from admin using 11 templates: 6 layout templates where you author the items (cards grid, text content, image gallery, CTA banner, stats counter, icon features) plus 5 data-showcase templates that auto-pull from your existing libraries (events, rsvp_form, video_gallery, podcast, products). Data-showcase templates hide the per-section items UI; the rsvp_form template prompts for an event slug on Edit and stores it in section.subtitle.
- **Event Ticketing & Donations** — events support three price modes: `free` (RSVP only), `paid` (Stripe Checkout for fixed price × guests), and `donation` (visitor-entered amount, optional minimum, "pay what you wish" flow). Free RSVPs are saved immediately; paid/donation RSVPs are saved with `payment_status='pending'` then redirected to Stripe Checkout — the row flips to `paid` via the `checkout.session.completed` webhook (idempotent, FOR UPDATE) and to `expired` via `checkout.session.expired`. Capacity is reserved at the moment the RSVP row is created so seats can't be double-sold while the visitor is in Checkout.
- **Service Bookings — Forms / Layout integration** — every service auto-mirrors its bookings into the Forms tab via a managed `custom_forms` row (`form_type='service_booking'`, `linked_service_id=<service.id>`, slug `service-booking-<svc-slug>`) created lazily by `_ensure_service_booking_form()` on the first booking attempt. Both partial saves (POST `/api/services/<slug>/booking-partial`, debounced 800ms once an email is typed) and final bookings INSERT/UPDATE rows in `form_submissions` keyed by a per-tab `session_id` so the same visitor's abandoned cart promotes to a `new` submission when they finish — no duplicate rows. Managed forms render in the Forms list with a purple "Service Booking" badge; Edit / Delete / field-mutation endpoints are blocked server-side (`_reject_if_managed`) so the auto-form can't be desynced from the service. The Submissions view continues to work normally. The same module also exposes `services` as a built-in Page Layout section (visibility/order driven by `page_sections` row, slug `services`, sort 12, default off) AND as a custom-section template choice (`Services / Bookings`) admins can drop into any custom section — both render the same active-services grid and use the existing booking modal. Tracking metadata sent with bookings/partials includes `session_id`, `page_url`, `referrer`, `language`, `screen_resolution`, and all five `utm_*` fields, mirroring the regular Forms analytics pipeline.
- **Service Bookings** — admin manages an unlimited number of bookable services from the **Services** tab. Each service uses one of four pricing models: **rsvp** (free reservation), **deposit** (Stripe Checkout for the deposit amount; remainder owed offline), **full** (full price via Stripe Checkout), or **contract** (admin uploads a PDF/DOC/DOCX template; the client downloads, signs offline, and re-uploads the signed copy via a tokenized `/booking/<token>/contract` page). Optional **add-ons** (priced extras) can be attached to any service and are multi-selected by the client at booking time; their snapshot is stored on the booking row so totals stay correct even if the add-on is later edited or removed. Calendar-backed services (`requires_calendar=true`) use **recurring weekly availability rules** (day-of-week + start/end + slot length) plus per-date **overrides** (`block` to remove a date or `open` to add a one-off). The public `/api/services/<slug>/availability?start&end` endpoint computes available time slots = (rules ∪ open-overrides) − block-overrides − slots already filled by `pending`/`confirmed` bookings up to `capacity_per_slot`. A successful deposit/full payment, or any admin status flip to `confirmed`, automatically removes the slot for future visitors. Booking dispatch returns one of three actions to the frontend: `redirect` (Stripe Checkout URL — webhook routes by `metadata.kind="service_booking"` to flip `payment_status='paid'`, `status='confirmed'`, and record `stripe_session_id` + `amount_paid_cents`), `contract_upload` (URL to the upload page), or `rsvp_confirmed` (immediate inline success). Confirmation emails go through the existing `messaging.send_email`/`messaging_log` path so they're tracked alongside everything else, and silently no-op when Resend isn't configured. Admin can filter all bookings by status, change status from a dropdown, and download each client's signed contract directly from the bookings table. Tables: `services`, `service_addons`, `service_availability_rules`, `service_availability_overrides`, `service_bookings` (all SERIAL PKs to match the existing convention).
- **Blog System** — database-driven blog with gallery-style preview cards on landing page, full post pages with SEO meta tags, admin management with draft/publish workflow
- **SEO Management** — admin tab for meta title, description, keywords, Open Graph, Twitter Cards; AI-powered SEO suggestion generator; auto-generated sitemap.xml and robots.txt; JSON-LD structured data
- **Visitor Analytics** — page view tracking with UTM params, device/browser/OS breakdown, referral sources, session duration; admin dashboard with charts and stats
- **Cost Transparency Dashboard & Weekly Digest** — admin **Cost** tab (under System group, gated by `cost_dashboard` feature flag) shows month-to-date AI spend with a Chart.js stacked-bar of daily totals, breakdown by surface (visitor_chat, admin_chat, page_gen, voice_tts, voice_stt, sms_*), breakdown by provider/model, and an editable pricing table where admins can adjust per-million-token / per-million-char / per-minute / per-segment unit prices on the fly (changes never affect already-stamped rows). Three ledger tables — `api_cost_events` (chat: prompt+completion tokens × stamped per-token unit price), `voice_cost_events` (TTS chars × per-million-chars OR STT audio_seconds × per-minute), and `sms_cost_events` (segments × per-segment, deduped by UNIQUE (tenant_id, message_sid)) — all stamp the unit price at write time so historical cost can never drift after a price edit. Webhook re-prices SMS rows ONLY by multiplying the stamped unit price by the revised segment count. Each surface call site (`/api/chat`, voice TTS prepare/consume, `/api/voice/stt`, SMS campaign send, scrape notify, review-request SMS) calls `enforce_cost_cap()` (HTTP) or `cost_cap_blocks_send()` (background jobs) before paying the provider; behavior is governed by `tenant_cost_caps.cap_behavior` ∈ {`alert_only` (never blocks; warn-line emails only), `throttle` (never blocks the request; sets `g._cost_throttled` so chat rate-limit drops to 5 req/window and TTS falls back to OpenAI when ElevenLabs was requested — degraded service rather than 429), `strict_block` (returns HTTP 402 `{"error":"cap_reached","cap":..,"spent":..}` on every paid call until the next month rolls)}. Async warn-line check after each cost write inserts an idempotent row into `cost_alerts` ((tenant_id, period, kind) UNIQUE) and emails the admin once per period when MTD spend crosses the configured `warn_at_percent` threshold. **Weekly digest** (`weekly_digest` feature flag): a scheduler tick fires every Monday 09:00–09:30 UTC, claims the per-tenant week slot via `INSERT ... ON CONFLICT (tenant_id, week_start) RETURNING id` BEFORE sending so a crash mid-send can never double-deliver; renders an HTML "What your AI did this week" email (spend + per-surface breakdown + top conversations + top forms) and sends via Resend to `cap.digest_email` → `cap.alert_email` → `ADMIN_EMAIL`. Whisper STT now requests `response_format="verbose_json"` so we get the actual `audio_seconds` for accurate per-minute billing. Tables: `model_prices` (provider, model, surface, unit prices, active flag), `api_cost_events`, `voice_cost_events`, `sms_cost_events`, `tenant_cost_caps`, `cost_alerts`, `weekly_digest_sends` — all SERIAL PKs. Endpoints: `/admin/api/cost/{summary,series,by-surface,by-model,prices,cap}` (GET/PATCH/PUT, `@admin_required` + `_cost_feature_required()` 404 when flag off).
- **HTML Sanitization** — DOMPurify sanitizes all AI-generated HTML before DOM injection
- **Accessibility** — dynamic ARIA labels, roles, live regions throughout the site; modular system auto-applies accessibility to admin-created custom sections
- **Chat History & Analytics** — view all AI conversations, message counts, device types
- **Dynamic Form Builder** — create custom forms from admin, add/remove/reorder fields, assign fields to steps for multi-step forms, view submissions with full marketing analytics
- **Partial/Abandon Capture** — auto-saves incomplete form data for lead recovery
- **Theme / Color Editor** — customize site colors, fonts, and glass effects from admin
- **Loading Experience** — elegant glassmorphic loading screen with shimmer animation, fades out to reveal content
- **Smooth Scroll Transitions** — enhanced snap-scroll with per-section entrance animations using IntersectionObserver
- **Card Micro-Interactions** — hover lift + white border glow on testimonial, team, experience, pricing, and FAQ cards
- **Gold Accent System** — `#c9a96e` accent strategically applied to section eyebrows, nav dots, footer headings, blog badges, chatbot border
- **Section Dividers** — subtle gold-tinted gradient lines between landing sections for visual breathing room
- **Blog Rich Text Editor** — custom toolbar-based editor in admin (bold, italic, headings, lists, links, images) replaces raw HTML textarea
- **Reading Progress Bar** — thin gold bar on blog post pages that fills as the reader scrolls
- **Chat Markdown Rendering** — AI responses render with proper formatting (headings, bold, lists, code blocks, tables) instead of raw markdown text; sanitized via DOMPurify
- **Consolidated Page Generator (generatePage)** — the SINGLE AI visualization command. Renders fully animated, theme-matched pages inside a sandboxed iframe (`sandbox="allow-scripts"`) with FULL CSS freedom: `<style>` tags, `@keyframes`, `background-image`, parallax, scroll effects. The site's theme variables (`--color-accent`, `--font-serif`, `--color-bg`, `--glass-bg`, etc.) AND the landing page hero image (`--hero-image`) are auto-injected into the iframe `:root` so every generated page visually flows from the landing page. Legacy `generateHTML` command names are aliased to the same renderer for backwards compatibility but the system prompt only teaches `generatePage`.
- **Live Page Render** — the immersive page renders progressively as the AI streams its response, instead of waiting for the full reply and popping in at the end. As soon as the streaming token buffer contains `{"action":"generatePage"…"html":"…`, the iframe overlay opens with a small "Building" pulse indicator and HTML chunks are appended into a `#__stream_root__` mount node via `postMessage` (the iframe's sandbox blocks direct DOM access, so `postMessage` is the only safe channel). A streaming JSON-string decoder (`extractStreamingJsonString`) decodes escapes (`\n`, `\"`, `\\uXXXX`, etc.) on partial buffers; only complete tag boundaries are flushed. The post-stream `case 'generatePage'` detects the live render and skips the one-shot re-render so animations the visitor just watched don't restart.
- **Auto-Canvas Fallback** — when AI sends long text without a command, it auto-renders in a premium frosted-glass canvas with gradient header, contextual eyebrow labels, accent-colored list bullets, and styled tables
- **Visual Request Priority** — system prompt enforces `generatePage` for "show me visually" and similar phrases; fallback canvas ensures polished display even when AI skips the command
- **Web Scraper** — admin-side AI scraper (`scraper.py`, admin "Web Scraper" tab) with two input modes: URL (server-side fetch with SSRF guards, 5MB cap, content-type allowlist, redirect re-validation) and Objective (OpenAI Responses API with `web_search_preview`). Cleans HTML to text and hands it to GPT in JSON mode against one of several target shapes (free-form notes, gallery card, pricing tier, blog post, contact details, custom JSON schema). Results can be pushed as drafts into matching tables (gallery cards, pricing tiers, blog posts). Recurring **scrape schedules** (hourly/daily/weekly/interval, UTC) auto-spawn jobs and can email/SMS the admin on completion or only on change (signature comparison). Schedules track a `consecutive_failures` counter and auto-pause once a configurable per-schedule `failure_threshold` (default 5, set to 0 to disable) is hit — the admin sees a "paused: repeated failures" indicator with the last error and a one-click Resume button (POST `/admin/api/scrape-schedules/<id>/resume`) that clears the failure trail and re-arms `next_run_at`. A successful run also resets the counter automatically. Optional **rendered fetch** auto-fallback for SPA pages: when the cleaned plain-GET response looks JavaScript-only and the admin has flipped the "Use rendered fetch" toggle, retry through a hosted headless-browser provider (ScrapingBee or Browserless) configured via env vars `SCRAPER_RENDER_PROVIDER` (default `scrapingbee`), `SCRAPINGBEE_API_KEY` or `BROWSERLESS_TOKEN`/`BROWSERLESS_URL`. The target URL is SSRF-validated before being handed to the provider, the response is still size-capped, and the admin sees a colored status line in settings showing whether the provider is actually configured.

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.
The entire template is industry-agnostic — naming, comments, and instructions avoid hotel/villa-specific language.

## Credentials Status (April 2026)

Secrets present in this Repl but **still holding placeholder values** — the matching features will fail or no-op until real values are pasted in:

- `RESEND_WEBHOOK_SECRET` — fail-open: webhook accepts events without signature check; status updates still post but anyone can spoof them
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — SMS campaigns + STOP-keyword opt-out + inbound-SMS webhook will return errors until real Twilio creds are set
- `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY` — reviews aggregator (Reviews → Insights tab) returns empty / error responses for the matching providers

Confirmed working with real values: `ADMIN_PASSWORD`, `ADMIN_EMAIL`, `ADMIN_PHONE`, `FLASK_SECRET_KEY`, `ELEVENLABS_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `SENTRY_DSN`, plus the Replit-managed integrations (OpenAI, Anthropic, Stripe, database).

When debugging or adding features that touch the placeholder list, assume the upstream call will fail and surface a friendly error — don't gate new functionality on those features being live.

## System Architecture

### Backend (Python Flask)
- **Framework**: Flask (Python)
- **Entry point**: `app.py`
- **Port**: 5000 (required for Replit webview)
- **Serves**:
  - Static files from `public/` (HTML, CSS, JS for the public site)
  - Admin dashboard templates from `templates/admin/`
  - REST API endpoints for both public reads and admin CRUD
  - Chat API endpoint for the AI chatbot
  - Uploaded images from `uploads/`

### Public Site (Static HTML/CSS/JS)
- **Location**: `public/` directory
- **Files**:
  - `index.html` — Main page structure (landing + gallery + modal + chatbot + split-screen)
  - `styles.css` — All visual styles, fully commented (18+ sections + chatbot + split-screen + testimonials + team + FAQ + footer)
  - `script.js` — All interactivity (API fetches, navigation, animations, chatbot, AI site control, theme loading, dynamic form rendering, section visibility, testimonials/team/FAQ/footer rendering)
- **Fonts**: Google Fonts (Playfair Display + DM Sans, dynamically swappable via Theme Editor)
- **Icons**: Lucide Icons (loaded via CDN)
- **No build step** — plain HTML/CSS/JS, works directly in any browser

### Admin Dashboard
- **URL**: `/admin` (redirects to `/admin/login` if not authenticated)
- **Login**: `/admin/login` — password set via `ADMIN_PASSWORD` environment variable (default: "admin")
- **Logout**: `/admin/logout`
- **Location**: `templates/admin/dashboard.html`, `templates/admin/login.html`
- **Tabs**: Page Layout (section ordering + custom section builder), Site Settings, Gallery Cards, Experiences, Pricing, Business Info (contact + hours + social links), Testimonials, Team, FAQ, Blog, Saved Pages, Sphere View, SEO (with AI generation), Chatbot, Chat History, Forms, Theme, Analytics

### Database (PostgreSQL)
- **Connection**: `DATABASE_URL` environment variable
- **Tables**:
  - `site_settings` — Global config (site name, tagline, hero content, logo initials, theme colors/fonts, section visibility toggles, business info, social links). Singleton row (id=1). Section toggles: section_testimonials, section_team, section_faq, section_footer (booleans). Business info: business_phone, business_email, business_address, business_hours (JSONB array of {day, open, close}), business_map_embed. Social links: social_links (JSONB object with platform keys).
  - `gallery_cards` — Slides for the gallery view and highlight cards on the landing page. Has slug (unique URL-friendly ID), title, subtitle, image_url, category, description, details (JSONB array), price, and sort_order.
  - `experiences` — Activity/service cards on the landing page. Has name, description, icon name, and sort_order.
  - `pricing_seasons` — Pricing tiers. Has label, date_range, price_range, and sort_order.
  - `testimonials` — Client reviews/testimonials. Has reviewer_name, reviewer_role, content, rating (1-5), image_url, sort_order.
  - `team_members` — Staff/team member profiles. Has name, title, bio, image_url, sort_order.
  - `faqs` — Frequently asked questions. Has question, answer, sort_order.
  - `page_sections` — Registry of all site sections (built-in + custom). Controls page layout order, section visibility, and template assignment. Built-in sections (hero, highlights, experiences, testimonials, team, faq, footer) are seeded on first run. Custom sections use templates: cards_grid, text_content, image_gallery, cta_banner, stats_counter, icon_features. Has slug (unique), title, section_type (built_in/custom), template, sort_order, enabled, settings (JSONB).
  - `custom_section_items` — Content items for custom sections. Linked to page_sections via section_id (CASCADE delete). Has title, subtitle, content, image_url, link_url, link_text, icon, sort_order, extra_data (JSONB for template-specific fields).
  - `blog_posts` — Blog post content. Has slug (unique), title, subtitle, excerpt, content (HTML), cover_image, author, category, tags, status (draft/published), seo_title, seo_description, published_at, sort_order. Sample post seeded on first run.
  - `events` — Event listings (workshops, webinars, store openings, retreats, etc.). Has slug (unique), title, description, image_url, start_at (timestamptz, required), end_at (optional), location, capacity (NULL = unlimited), price (free-form text like "Free" or "$25"), status (draft/published/cancelled), sort_order. Public site shows published + cancelled events whose end (or start) is today or later, ordered by start_at.
  - `event_rsvps` — Visitor RSVPs for events. Linked to events via event_id (CASCADE delete). Has name, email, phone, guests, notes. Capacity is enforced at write time in the API by summing guests across rows.
  - `page_views` — Visitor analytics tracking. Has session_id, visitor_id, page_url, referrer_url, UTM params (source/medium/campaign/term/content), ip_address, browser, os, device_type, screen_resolution, language, country, duration_seconds.
  - `chatbot_settings` — AI chatbot configuration. Singleton row (id=1). Has enabled, mode, agent_name, agent_role, agent_avatar, greeting, quick_prompts (JSONB), api_endpoint, embed_code, system_prompt.
  - `chat_conversations` — Chat sessions with visitor info (session_id, ip, device_type, user_agent).
  - `chat_messages` — Individual chat messages linked to conversations (role, content, command_json).
  - `custom_forms` — Dynamic form definitions (name, slug, description, status, submit_button_text, success_message).
  - `form_fields` — Form field definitions (form_id FK, field_type, label, name, placeholder, required, options JSONB, default_value, sort_order, width, help_text, step). The `step` column controls multi-step form grouping (default 1).
  - `form_submissions` — Dynamic form submissions (form_id FK, submission_data JSONB, status, device_type, browser, os, screen_resolution, language, UTM params, referrer, IP, session_id, updated_at).
  - `uploaded_images` — Record of uploaded image files (filename, original_name, file_size).
  - `generated_pages` — AI-generated HTML pages saved from chatbot interactions. Has title, html (full content), prompt (user's original question), slug (unique URL), status (draft/published), created_at, updated_at.
  - `sphere_settings` — 3D sphere view configuration. Singleton row (id=1). Has enabled, heading_text, view_mode (sphere/sections), particle_count, rotation_speed, sphere_radius, image_size, image_source (gallery/custom), position_randomness, particle_opacity, zoom_min, zoom_max, card_scale, card_gap.
  - `sphere_images` — Custom images for the sphere view (when image_source='custom'). Has image_url, caption, sort_order.
  - `presentations` — **Phase A: Agentic Skills.** Slide decks the AI launches on the visitor's screen with voice narration. Has slug (unique), title, description (one short sentence the AI uses to decide when to offer the deck), cover_image_url, source ('admin' for admin-typed decks, also used for imported decks), auto_play (boolean — when true the AI launches without asking first), enabled, created_at, updated_at. **Decks can also be created by upload via `POST /admin/api/presentations/import`**: any slide format auto-converts to one rendered JPG per slide so "original" display mode shows pixel-perfect visuals. Pipeline: any Office format (`.pptx`/`.ppt`/`.key`/`.odp`/`.doc`/`.docx`/`.odt`/`.rtf`) → LibreOffice headless (`soffice`, installed as Nix system dep `libreoffice-still`, run with per-call temp UserInstallation profile + 180s timeout) → PDF → PyMuPDF (`fitz`) renders each page at 2× matrix capped at 1600px wide / 85% JPEG quality → saved under `/uploads/`. Direct PDF uploads skip the LibreOffice step; image sets (JPG/PNG/WEBP) skip everything and become one slide per file ordered by filename. PPTX gets a bonus pass: `python-pptx` extracts speaker notes per slide and pre-populates `narration_text` so the AI narrator has a starting script. Helpers live above the route: `_convert_office_to_pdf`, `_render_pdf_to_slide_rows`, `_extract_pptx_notes`. The "Import deck" button on the Presentations admin tab triggers this flow and opens the resulting deck in the editor for review.
  - `presentation_slides` — Ordered slides belonging to a presentation. Linked via presentation_id (CASCADE delete). Has order_index, title, body (text shown on screen), image_url (optional), narration_text (what the voice agent reads aloud — falls back to body if blank).
  - **Presentation Player UX (public/script.js + public/styles.css)** — The full-screen overlay player is frosted-glass, edge-to-edge, with floating chrome (top-left progress pill, top-right close, bottom controls) so the slide image is the hero. The overlay also has an **in-deck chat pill** (`.presentation-chat-pill`) — the visitor can ask questions without leaving the deck. The pill posts to `/api/chat` with `presentation_active=true` AND a new `presentation_slide` payload (deck title, slide #/total, slide title, body, narration, has_image flag). The backend injects this into the system prompt as an "ON SCREEN RIGHT NOW" block so the AI presents what's actually visible rather than guessing. The reply streams into a glass bubble above the pill, voice goes through the existing VoiceAgent `streamSpeak*` pipeline, and `_scheduleAutoResumeAfterChatReply` brings the deck back when the AI finishes. The narration generator system prompt (admin "Generate narration" button) also frames the model as a "live presenter" rather than a generic narrator.
  - `agent_skills` — Registry of every skill (tool) the chat AI can call. Auto-synced on startup from `SKILL_METADATA` in app.py. Has name (unique), display_name, description, category (lookup, presentation, ...), enabled (admin toggle that drives `get_active_chat_tools`), builtin (true for code-defined skills), config_json (per-skill overrides), created_at, updated_at. **Builtins and custom skills share the same admin editor surface** — both expose display_name, description, category, response_text, and enabled. The only immutable field on builtins is `name` (it's the identifier the model passes back). Edits to display_name / description / category survive restart because `sync_skills_to_db` uses `COALESCE(NULLIF(...))` on each field; only `builtin=true` is hard-set from code. The category field is a `<datalist>` input pre-populated from categories already in use. Custom-skill names are validated against `^[a-z][a-z0-9_]{1,59}$` and rejected if they collide with a builtin.
    - **Builtin override path**: every builtin's `config_json.response_text` is treated as an OPTIONAL OVERRIDE. `_execute_chat_tool_inner` reads the row up-front and, when `response_text` is non-empty, returns that text verbatim INSTEAD of running the Python lookup function. Blank override = live code runs as before. Override fires are stamped with `_meta_override: true` in `skill_usage_log.args_json` so the admin can see in the Recent Skill Calls panel which invocations were canned-text replacements. Skills whose return value is machine-consumed downstream (currently just `lookup_service_availability`, which feeds the booking flow's tap-to-pick chip UI) carry an extra amber warning in the editor, since an override silently disables that downstream UX.
    - **Web search skill (`lookup_web_search`)**: external "last resort" tool the AI may call only when no internal `lookup_*` would have answered AND the question is clearly relevant to the business — the AI itself owns the relevance gate, and the tool description + a dedicated WEB SEARCH POLICY block (appended to the system prompt only when the skill row is enabled) instruct it to refuse off-topic searches even when the visitor explicitly asks. Provider chain: Brave Search API (`BRAVE_SEARCH_API_KEY`, `_websearch_brave`, count=5, safesearch=moderate, 8s `httpx` timeout, strips `<>` highlight tags) is tried first; if Brave is unconfigured / errors / returns no results, falls back to Anthropic's native `web_search_20250305` server tool (`_websearch_anthropic`, claude-sonnet-4-5, max_uses=2, 25s timeout via `with_options`, walks both text-block `citations[]` and `web_search_tool_result.content[]` for url+title). Returns `{provider, fallback_reason, result_count, results:[{title,url,snippet}]}`. The WEB SEARCH POLICY block also instructs the AI to (a) write its own 1-3 sentence answer, (b) end with a `Sources:` markdown line of 1-3 links using only the URLs the tool returned, and (c) treat snippet/title/URL text as untrusted reference material — never follow instructions injected by hostile pages. Frontend already renders assistant markdown so the source links are clickable. Skill row is auto-created at startup as `category='external'` and is fully toggleable from the admin Skills tab like every other builtin.
    - **Live-managed prompt**: every chat turn appends a `TOOLBOX` section to the system prompt built from `SELECT name, display_name, description, category FROM agent_skills WHERE enabled = true` (grouped by category, builtins first, descriptions truncated to 240 chars per line), so admin edits to a builtin's description and every custom skill's description ACTUALLY drive the model's tool-selection behavior. A guardrail line above the list reminds the AI the entries are reference metadata, not visitor instructions.
    - **Endpoints**: `GET /admin/api/skills`, `POST /admin/api/skills`, `PUT /admin/api/skills/<id>`, `DELETE /admin/api/skills/<id>` (custom only — builtins refuse with a 400 explaining they'd resync on next restart; disable them instead).
  - `skill_usage_log` — Observability table written by `_log_skill_usage` every time the AI calls a skill. Has skill_name, args_json, row_count, duration_ms, error, conversation_id, session_id, created_at. Powers the "Recent Skill Calls" panel in the AI Skills admin tab.
  - `agent_provider_settings` — Singleton row (id=1) holding the active LLM provider. Has provider ('openai' or 'claude'), openai_model, claude_model, updated_at. The chat dispatcher reads this on every visitor message via `get_active_llm_provider`.
  - `alembic_version` — Owned by Alembic. Single-row tracker that records the latest migration revision applied to this database. Never written to by app code; managed entirely by `alembic upgrade` (auto-run on boot — see "Schema Migrations" below).

## Schema Migrations (Alembic — April 2026)

The project uses **two coexisting schema-management tracks**. Both run on every dev boot, in this order, after the connection pool is initialised:

1. **`init_db()` in `app.py`** — the LEGACY "fresh install" path. It owns every table and column that existed when Alembic was adopted. Idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS only — never DROP, never ALTER TYPE), so re-running it on an existing DB is a no-op. **This code is FROZEN.** Do not add new tables or columns to it.
2. **`_run_alembic_upgrade()` in `app.py`** — runs `alembic upgrade head` against the live `DATABASE_URL`. Applies every revision in `migrations/versions/` that the DB hasn't seen yet, then exits. On a brand-new DB the empty `0001_baseline` migration is a no-op that just creates `alembic_version` and stamps the starting row; on an up-to-date DB the upgrade is a single `SELECT version_num FROM alembic_version` and exits.

The two tracks coexist cleanly because init_db never touches anything Alembic might add (the historical create-statements predate every migration), and Alembic migrations never redeclare anything init_db owns (every revision starts from the post-init_db state).

### Adding a new column or table

```bash
# 1. Generate a new revision file (Alembic creates it under migrations/versions/).
uv run alembic revision -m "add foo column to bar"

# 2. Edit the generated file. Use op.add_column() / op.create_table() / op.execute() — see Alembic's "Operation Reference".
#    The downgrade() must be a precise inverse so deploys can be rolled back.

# 3. Test locally:
uv run alembic upgrade head     # apply
uv run alembic downgrade -1     # roll back one revision (verify downgrade works)
uv run alembic upgrade head     # re-apply

# 4. Restart the dev workflow — `_run_alembic_upgrade()` confirms the boot path picks it up.
# 5. Commit BOTH the new revision file AND any new code that depends on the column/table.
```

### Why the dual-track scheme

The legacy `init_db()` had grown to ~7500 lines and was the source of every "I added a column but forgot to also add it to init_db" outage. Freezing it and routing all new schema work through Alembic stops the file from growing further while preserving the existing fresh-install guarantees for the historical tables. Operators upgrading an existing install pay no extra cost — Alembic upgrade-to-head against a tip database is a single SELECT.

### Files

- `alembic.ini` — Alembic config (placeholder DATABASE_URL; the real one is read from env in `migrations/env.py`).
- `migrations/env.py` — Custom env that connects via SQLAlchemy + psycopg2 using the live `DATABASE_URL`. `target_metadata = None` because the codebase has no SQLAlchemy declarative models — every revision is hand-written.
- `migrations/script.py.mako` — Template for new revision files.
- `migrations/versions/0001_baseline.py` — Intentionally empty baseline.
- `migrations/README` — Quick-start reminder for contributors.

### Escape hatches

- `SKIP_ALEMBIC=1` — bypass the upgrade on boot. Only for emergency recovery (e.g. rolling back a bad release while the bad revision is still in the tree). The app will boot but may serve 500s if its code expects a column the DB doesn't have.
- `uv run alembic upgrade head --sql` — render the pending SQL to stdout for review without touching the DB.
- `uv run alembic current` / `uv run alembic history` — inspect the live revision and the full history.

### Known limitation (pre-existing, not introduced here)

Like `init_db()`, `_run_alembic_upgrade()` is called only from the `if __name__ == "__main__":` block in `app.py`. That means the dev workflow runs it but production gunicorn (`gunicorn app:app`) and the pytest fixture do not — both rely on the dev boot to keep the DB in sync. This matches the existing init_db blast radius; lifting both to module-level boot is a separate task.

### API Endpoints

**Public (read-only, used by the public site's JavaScript):**
- `GET /api/site-settings` — Returns site configuration
- `GET /api/gallery-cards` — Returns all gallery cards ordered by sort_order
- `GET /api/experiences` — Returns all experiences ordered by sort_order
- `GET /api/pricing` — Returns all pricing seasons ordered by sort_order
- `GET /api/testimonials` — Returns all testimonials ordered by sort_order
- `GET /api/team` — Returns all team members ordered by sort_order
- `GET /api/faq` — Returns all FAQ entries ordered by sort_order
- `GET /api/business-info` — Returns business contact info, hours, and social links
- `GET /api/page-sections` — Returns all sections in sort order (controls page layout and visibility)
- `GET /api/custom-section/<section_id>/items` — Returns items for a custom section
- `GET /api/blog` — Returns all published blog posts
- `GET /api/blog/<slug>` — Returns a single published blog post
- `GET /api/events` — Returns published + cancelled upcoming events with rolled-up rsvp_count
- `GET /api/events/<slug>` — Returns a single event with rsvp_count
- `POST /api/events/<slug>/rsvp` — Create an RSVP (validates name+email, enforces capacity, blocks cancelled)
- `GET /api/seo` — Returns SEO settings for meta tag injection
- `GET /api/sphere-settings` — Returns sphere view configuration and image URLs
- `GET /api/chatbot-settings` — Returns chatbot configuration (enabled, mode, agent info, etc.)
- `GET /api/theme` — Returns theme customization values (colors, fonts)
- `GET /api/forms/<slug>` — Returns form config (fields, types, options) for dynamic rendering
- `GET /sitemap.xml` — Auto-generated XML sitemap (home, published blogs, published generated pages)
- `GET /robots.txt` — Standard robots.txt with sitemap reference
- `GET /blog/<slug>` — Public blog post page with SEO meta tags and JSON-LD structured data
- `GET /event/<slug>` — Public event page with cover image, meta details, and a built-in RSVP form

**Chat API:**
- `POST /api/chat` — Streaming SSE chat. Accepts `{message, history, session_id}`, streams token/text/html/command/done events. Saves messages to chat_conversations/chat_messages. AI commands include: navigate, showSlide, generateVisual, generateHTML, generatePage, submitForm, scrollToSection, heroMessage. The AI can also collect form data conversationally and submit via the submitForm command. generatePage renders animated pages in a sandboxed iframe with full CSS freedom (animations, @keyframes, background-image).

**Tracking API:**
- `POST /api/track/pageview` — Record a page view with session/visitor IDs, UTM params, device info (rate-limited to 1 per session+page per 30s)
- `POST /api/track/duration` — Update session duration via sendBeacon on page unload

**Form Submission API:**
- `POST /api/forms/<slug>/submit` — Submit a dynamic form with auto-captured marketing data (UTM, device, browser, OS, screen resolution, language, referrer, IP, session ID)
- `POST /api/forms/<slug>/partial` — Auto-save partial/abandoned form data (upserts by session_id)
- `POST /api/bookings` — Legacy form submission (still works)
- `POST /api/booking-step` — Legacy funnel tracking

**Admin (CRUD, protected by session login):**
- `GET/PUT /admin/api/site-settings` — Read and update site settings
- `GET/POST/PUT/DELETE /admin/api/gallery-cards` — Gallery card management
- `GET/POST/PUT/DELETE /admin/api/experiences` — Experience management
- `GET/POST/PUT/DELETE /admin/api/pricing` — Pricing management
- `GET/PUT /admin/api/chatbot-settings` — Chatbot configuration (includes system_prompt)
- `GET /admin/api/default-system-prompt` — Get the hardcoded default system prompt
- `POST /admin/api/upload-image` — Upload an image file, returns URL
- `GET/POST/PUT/DELETE /admin/api/testimonials[/<id>]` — Testimonial management
- `GET/POST/PUT/DELETE /admin/api/team[/<id>]` — Team member management
- `GET/POST/PUT/DELETE /admin/api/faq[/<id>]` — FAQ management
- `GET/PUT /admin/api/business-info` — Business contact info (phone, email, address, hours, map embed)
- `GET/PUT /admin/api/social-links` — Social media profile URLs
- `GET/PUT /admin/api/section-visibility` — Toggle sections on/off (testimonials, team, faq, footer) — legacy, now use page-sections toggle instead
- `GET/POST/PUT/DELETE /admin/api/page-sections[/<id>]` — Page section registry (layout order, custom sections)
- `PUT /admin/api/page-sections/<id>/toggle` — Quick enable/disable toggle for a section
- `GET/POST/PUT/DELETE /admin/api/custom-sections/<section_id>/items[/<item_id>]` — Custom section items CRUD
- `GET/PUT /admin/api/seo` — Read and update SEO settings (meta title, description, keywords, OG image, Twitter handle, canonical URL, robots)
- `POST /admin/api/seo/generate` — AI-powered SEO content suggestion generator (uses OpenAI to analyze site content)
- `GET/POST/PUT/DELETE /admin/api/blog[/<id>]` — Blog post management (CRUD with draft/publish workflow)
- `GET/POST/PUT/DELETE /admin/api/events[/<id>]` — Event management (CRUD with draft/published/cancelled status)
- `GET /admin/api/events/<id>/rsvps` — List all RSVPs for one event (newest first)
- `DELETE /admin/api/event-rsvps/<id>` — Remove a single RSVP
- `GET /admin/api/analytics` — Aggregated visitor analytics (views, unique visitors, top pages, referrers, UTM, devices, browsers, OS)
- `GET /admin/api/analytics/chart` — Daily page view counts for bar chart (last 30 days)
- `PUT /admin/api/reorder/<type>` — Batch reorder gallery-cards, experiences, pricing, testimonials, team, faq, page-sections, custom-section-items, or blog-posts
- `GET /admin/api/chat-history` — List conversations with stats
- `GET /admin/api/chat-history/<id>` — Full conversation detail with messages
- `GET/POST /admin/api/forms` — List all forms / create new form
- `GET/PUT/DELETE /admin/api/forms/<id>` — Get, update, or delete a form
- `POST /admin/api/forms/<id>/fields` — Add a field to a form
- `PUT /admin/api/forms/<id>/fields/<field_id>` — Update a field
- `DELETE /admin/api/forms/<id>/fields/<field_id>` — Delete a field
- `PUT /admin/api/forms/<id>/fields/reorder` — Reorder fields (drag-and-drop)
- `GET /admin/api/forms/<id>/submissions` — List form submissions with field data
- `PUT /admin/api/submissions/<id>/status` — Update submission status
- `DELETE /admin/api/submissions/<id>` — Delete a submission
- `GET /admin/api/forms/<id>/analytics` — Marketing analytics (device, browser, OS, UTM, status, referrer, language breakdowns)
- `POST /api/generated-pages` — Auto-save AI-generated HTML page (called from frontend)
- `GET/PUT/DELETE /admin/api/generated-pages/<id>` — View, update, or delete a saved page
- `GET /admin/api/generated-pages` — List all saved AI-generated pages
- `GET /page/<slug>` — Public URL for published AI-generated pages
- `GET /admin/api/bookings` — Legacy submissions list
- `PUT /admin/api/bookings/<id>/status` — Legacy submission status update
- `GET/PUT /admin/api/sphere-settings` — Sphere view configuration (enable/disable, heading, particles, images)
- `GET/POST/DELETE /admin/api/sphere-images[/<id>]` — Custom sphere image management
- `PUT /admin/api/reorder/sphere-images` — Reorder custom sphere images
- `GET/PUT /admin/api/theme` — Read and update theme colors/fonts

**Static files:**
- `GET /uploads/<filename>` — Serve uploaded images

## AI Chatbot System

### Enabling the Chatbot
1. Go to `/admin` → Chatbot tab
2. Toggle "Enable Chatbot" to ON
3. Choose a mode: Built-in Chat or External Embed
4. Save settings
5. Reload the public site

### Connection Modes

**Built-in Mode** (`mode: builtin`):
- Uses the template's built-in chat UI (floating glass-panel bar at the bottom)
- Messages are POST'd to the configured API endpoint (default: `/api/chat`)
- The default `/api/chat` endpoint includes demo responses with site control commands
- Replace with your own AI backend by changing the API endpoint URL

**Embed Mode** (`mode: embed`):
- Paste any external chatbot widget code (Intercom, Drift, Tidio, custom)
- The code is injected into the page and the external widget handles everything
- The built-in chat UI is hidden in this mode

### AI System Prompt
- Editable from admin → Chatbot tab → "AI System Prompt" section
- Falls back to the hardcoded default prompt if the database value is empty
- "Load Default Prompt" button pre-fills the textarea with the built-in prompt for editing

### AI Site Control System

The AI chatbot can control what the user sees on the website through special commands in API responses.

**Response format:**
```json
{
  "reply": "Text message shown in chat bubble",
  "command": { "action": "...", ... }
}
```

**Available commands:**

1. **scrollToSection** — Scroll to a landing-page section (testimonials, team, faq, events, podcast, contact info, etc.). Use this for anything that lives in a built-in or custom landing-page section, NOT individual gallery items.
   ```json
   {"action": "scrollToSection", "target": "section-testimonials"}
   ```
   Valid built-in targets: `section-hero`, `section-highlights`, `section-experiences`, `section-testimonials`, `section-team`, `section-faq`, `section-blog`, `section-events`, `section-video-gallery`, `section-podcast`, `section-store`, `section-business-info`. Footer is `site-footer`. Custom sections use `section-custom-{id}`. The system prompt is built dynamically and ships the exact target ID alongside each enabled section in the LANDING PAGE LAYOUT block (built in `app.py` ~line 3092 from `page_sections.slug`/`id`, with `footer` special-cased to `site-footer` to mirror `BUILTIN_SECTION_MAP` in `public/script.js` ~line 1398).

2. **navigate** — Scroll to a gallery card and show it in split-screen
   ```json
   {"action": "navigate", "target": "gallery-item-slug"}
   ```
   Valid targets: any slug from the gallery_cards table

2. **showSlide** — Show a structured presentation slide
   ```json
   {"action": "showSlide", "title": "Title", "subtitle": "Subtitle", "points": ["Point 1", "Point 2"]}
   ```

3. **generateVisual** — Render a templated visual slide (table or list)
   ```json
   {"action": "generateVisual", "title": "Pricing", "columns": ["Item", "Price"], "rows": [["Item A", "$600"]], "footer": "Prices vary"}
   ```
   The AI sends structured data and the frontend renders it using a pre-built frosted glass template. Supports two layouts:
   - **Table**: `columns` + `rows` for comparisons, pricing, schedules
   - **List**: `items` [{label, value}] for key-value pairs

4. **generateHTML** — Render fully custom, theme-matched HTML on a fullscreen canvas
   ```json
   {"action": "generateHTML", "title": "Title", "html": "<div style='...'>...</div>"}
   ```
   The AI has full creative freedom — comparison tables, itineraries, pricing cards, timelines, etc.
   Theme colors, fonts, and glass effects are injected into the system prompt so output always matches the brand.
   A comprehensive design system (containers, typography, accent usage, layout patterns, decorative touches) is included in the prompt.
   Generated pages are auto-saved to the database for admin review (Saved Pages tab).
   Content is displayed on a fullscreen canvas with right padding to clear the side chat panel (26rem on desktop, responsive on mobile).

### Adding New Commands

1. Define the command format (JSON structure)
2. Add a handler in `script.js` → `executeCommand()` function
3. Update the system prompt (from admin → Chatbot → AI System Prompt) to teach the AI about the command
4. Test with a sample API response

### AI Integration (OpenAI)

The chatbot connects to OpenAI GPT-4o-mini via Replit AI Integrations. Single unified streaming endpoint:
- `POST /api/chat` — SSE streaming for ALL messages. Tokens arrive live so the user sees text being typed out. After streaming completes, the server sends final `text`, `command`, and `done` events. Messages are saved to chat_conversations/chat_messages for analytics.

The AI uses `generateVisual` for simple data displays and `generateHTML` for rich, creative content (comparisons, itineraries, schedules, multi-section layouts). Theme colors, fonts, and glass styling are injected into the system prompt so all generated HTML matches the brand automatically. The command parser handles multiple JSON block formats (standard fenced blocks, backtick-adjacent format, bare JSON fallback) to maximize reliability.

## Admin Features

### Admin Chat (in-dashboard AI assistant)
A dedicated **Admin Chat** tab in the dashboard sidebar (under "AI & Chat") gives the owner two ways to talk to AI directly from the admin:

1. **Admin assistant mode** — talks to a separate, elevated agent backed by `POST /admin/api/chat/send`. The agent has admin-only tools split into two groups:
   - **Read tools (run immediately):** `admin_list_tables`, `admin_describe_table`, `admin_run_sql` (SELECT-only — multi-statement and write keywords are rejected, 100-row cap, 5-second statement timeout, runs in a non-autocommit connection that is rolled back at the end), `admin_list_skills`, `admin_recent_visitor_chats`, `admin_recent_orders`, `admin_recent_form_submissions`, `admin_overview_stats`, `admin_skill_usage_stats`.
   - **Write tools (approval-gated):** `admin_propose_insert`, `admin_propose_update`, `admin_propose_delete`, `admin_propose_run_sql`. These never touch the database directly. They write a row to `admin_pending_actions` (status=`pending`) with a human-readable preview, then return `{awaiting_approval:true, action_id, preview}` to the model. The dashboard renders an Approve / Reject card; only when the owner clicks Approve does `POST /admin/api/chat/action/<id>/approve` execute the change inside a transaction. Approve/Reject also writes a synthetic follow-up note into `admin_chat_messages` so the assistant sees the outcome on the next turn.

   Write safety: `_admin_validate_write_table` blacklists audit/log/history tables (`page_views`, `*_log`, `chat_messages`, `chat_conversations`, `admin_chat_messages`, `admin_pending_actions`, `scrape_jobs`); identifiers are interpolated via `psycopg2.sql.Identifier` and values via parameters (so injection through column names is blocked); `admin_propose_run_sql` blocks `DROP DATABASE/SCHEMA/ROLE/USER`, `TRUNCATE ALL`, `GRANT/REVOKE`, `CREATE/ALTER ROLE/USER/EXTENSION/SYSTEM`, `COPY FROM/TO`, `pg_*_server_files`, and `LO_IMPORT/EXPORT`. The free-form SQL path also runs `_admin_sql_blacklist_check` (regex-extracts `UPDATE/INSERT INTO/DELETE FROM/TRUNCATE/MERGE INTO/ALTER TABLE/DROP TABLE` targets, normalizes schema-qualifier and quoted idents) at *both* proposal time and execution time, so the same table-level blacklist that protects the typed-write tools cannot be bypassed by phrasing the change as raw SQL. Approve/Reject use an atomic `UPDATE … WHERE id=%s AND status='pending' RETURNING …`, so a double-click or duplicate request returns 409 instead of executing twice. Every admin-tool call is logged into `skill_usage_log` under `session_id` prefixed with `admin_chat_` so it is easy to filter out of visitor analytics.

2. **Preview-as-visitor mode** — sends the message straight to the public `/api/chat` endpoint so the admin can sanity-check exactly what real visitors would see. Session id is prefixed with `admin_preview_` so these conversations are obvious in the Chat History tab.

Conversations are persisted in the `admin_chat_messages` table (one row per turn, with `mode`, `role`, `content`, `tool_calls_json`, `tool_call_id`, `tool_name`, `created_at`). Pending writes live in `admin_pending_actions` (`session_id`, `action_type`, `target_table`, `target_id`, `payload_json`, `preview`, `status` ∈ {pending, approved, rejected, executed, failed}, `result_json`, `error_text`, `created_at`, `decided_at`). Each mode keeps its own session id in the browser's localStorage so a thread survives reloads. The admin agent uses the active OpenAI model from `agent_provider_settings`, with an 8-round tool-call cap and a system prompt that teaches the propose → approve workflow.

### Custom Skills (Knowledge / Webhook / SQL)
The chatbot can be extended with three kinds of admin-managed skills, all surfaced under **AI & Chat → Custom Skills** in the dashboard and editable from admin chat as well:

1. **Knowledge entries** (`custom_knowledge_entries`: `id`, `topic`, `content`, `enabled`). A single sentinel `agent_skills` row named `lookup_knowledge` (config `{"type":"knowledge"}`) exposes them to the consumer chat agent. The dispatcher (`_exec_custom_knowledge`) does a case-insensitive ILIKE search on `topic` and `content` for the `query` arg and returns the top `max_results` (default 5, hard cap 20).
2. **Webhook skills** (`custom_webhook_skills`: `name` UNIQUE, `description`, `url`, `method` GET/POST, `headers_json` JSONB, `args_schema_json` JSONB, `timeout_seconds`, `enabled`). Each enabled row is mirrored into `agent_skills` with config `{"type":"webhook","webhook_id":N}`. The dispatcher (`_exec_custom_webhook`) validates the URL with `_webhook_url_safe` (resolves the hostname through `socket.getaddrinfo` and rejects every result whose `ipaddress.ip_address` is private/loopback/link-local/multicast/reserved, plus the literal `localhost`/`*.local`/`*.localhost`/`*.internal` suffixes), enforces a 1–15 s timeout cap, disables redirects, sets `User-Agent: site-webhook-skill/1.0`, and truncates the response body to 4 KB. The same URL validator runs at save time inside `_normalize_webhook_payload`, so the admin sees a clear error before a bad row ever lands.
3. **SQL skills** (`custom_sql_skills`: `name` UNIQUE, `description`, `sql_template`, `args_schema_json`, `enabled`). Each enabled row is mirrored into `agent_skills` with config `{"type":"sql","sql_skill_id":N}`. The dispatcher (`_exec_custom_sql`) reuses the same guardrails as `admin_run_sql`: SELECT-only, single statement, 100-row cap, 5-second `statement_timeout`, runs in a non-autocommit connection that is rolled back at the end. Args are bound through psycopg2 named-style placeholders (`%(arg)s`) so user-controlled values can never be interpolated as SQL.

`sync_custom_skills_to_agent_skills()` runs at startup and after every CRUD on the three custom-skill tables; it inserts/updates/disables `agent_skills` rows so deleted or disabled custom skills disappear from the consumer agent immediately. `get_active_chat_tools()` reads each non-builtin row's `config_json` and attaches the right argument schema (the linked row's `args_schema_json` for webhook/SQL, a hardcoded `{query, max_results}` schema for knowledge).

### Snapshot & Revert (agent-config tables)
Any approved write from the admin chat assistant against one of the "settings" tables — `chatbot_settings`, `agent_skills`, `agent_provider_settings`, `site_settings`, `voice_settings`, `custom_knowledge_entries`, `custom_webhook_skills`, `custom_sql_skills` — is preceded by a row snapshot. `_admin_snapshot_row(table, row_id, action_id, reason)` SELECTs the current row and writes the full JSON payload to `admin_setting_snapshots` (`id`, `table_name`, `row_id`, `snapshot_json` JSONB, `action_id` nullable FK, `reason`, `created_at`, `reverted_at`). Direct dashboard PUT/DELETE on the three custom-skill tables also records a snapshot (with `action_id=NULL`).

The dashboard's **Recent Changes** panel (sidebar under AI & Chat) lists the last 50 snapshots and exposes a one-click Revert. Revert is served by `POST /admin/api/snapshots/<id>/revert` (synchronous, no second approval) and routed through `_admin_execute_revert`: if the snapshotted row still exists it issues an `UPDATE … WHERE id=%s`; if the row has been deleted it re-INSERTs with the original `id` (SERIAL PKs accept explicit values). JSONB columns are detected from `information_schema.columns` and bound through `%s::jsonb` casts so dict/list values round-trip correctly. After the revert the snapshot's `reverted_at` is set and `_admin_post_write_sync(table)` re-runs `sync_custom_skills_to_agent_skills()` so the consumer agent picks up the restored row.

The admin chat assistant has a matching `admin_recent_snapshots()` read tool and an `admin_propose_revert_snapshot(snapshot_id, reason)` write tool that goes through the same approval flow as `admin_propose_update`. The system prompt teaches both the custom-skill tables and the snapshot/revert workflow.

### Image Upload
- Upload buttons appear next to image URL fields (hero image, gallery card image)
- Images are validated (jpg/png/gif/webp only), saved with unique filenames to `/uploads/`
- Upload records are stored in `uploaded_images` table

### Drag-and-Drop Reordering
- Gallery Cards, Experiences, and Pricing tables have drag handles (hamburger icon)
- Drag rows to reorder; new sort_order is saved immediately via PUT request
- Powered by SortableJS (loaded from CDN)

### Chat History & Analytics
- All chat conversations are saved with visitor IP, device type, user agent
- Admin → Chat History tab shows conversation list with stats (total, messages today, average per conversation)
- Click "View" to expand and see the full message thread

### Dynamic Form Builder
- Admin → Forms tab for creating and managing custom forms
- **Form creation**: Name, slug (auto-generated), description, submit button text, success message, active/inactive status
- **Field management**: Add/edit/delete fields with drag-and-drop reordering
- **Field types**: text, email, tel, number, date, select (dropdown), textarea, checkbox, radio, hidden
- **Field options**: Label, name (slug), placeholder, required toggle, width (full/half), options (for select/radio), default value, help text
- **Dynamic rendering**: Public site fetches form config from `/api/forms/<slug>` and renders fields dynamically
- **Half-width fields**: Two half-width fields are displayed side-by-side in a 2-column grid
- **Select field auto-population**: Select fields named "service" are auto-populated with gallery cards data
- **Auto-captured marketing data**: UTM params (source/medium/campaign/term/content), device type, browser, OS, screen resolution, language, referrer, page URL, IP address, session ID
- **Partial/Abandon Capture**: Auto-saves incomplete form data on field blur/change with 1.5s debounce; upserts by session_id; final submit upgrades partial to new status
- **Submissions**: JSONB storage for flexible field data; viewed in admin with dynamic table headers
- **Submission detail**: Expandable view showing all form data + marketing metadata
- **Analytics dashboard**: Total submissions, today's count, abandoned count, abandon rate, device breakdown, top UTM sources, browser/OS stats, status distribution
- **Status tracking**: partial (abandoned) → new → reviewed → contacted → archived
- Default "Contact Request" form is seeded on first run with 8 fields (name, email, service, start date, end date, quantity, phone, details)

### Overview Dashboard (default landing tab)
- Admin → Overview tab is the new default landing view (was Page Layout)
- KPI cards (5–6) show visitors today / this week, page views today, new leads, chat sessions, **skill calls today / this week**, and revenue (auto-hidden when zero)
- **Phase A feature row** below KPIs — three glass tiles with deep-link actions:
  - **AI provider** (OpenAI / Claude) with current model name → "Change provider" jumps to LLM Provider tab
  - **Active skills** (e.g. "14 / 14") with weekly error count, "Attention" pill when errors > 0 → "Manage skills" jumps to Skills tab
  - **Presentations** (live count + total decks) → "Open presentations" jumps to Presentations tab
- 14-day visitor trend chart powered by Chart.js (dark-themed axes/grid)
- Recent submissions list with form name, preview, and relative time
- **Top skills, last 7 days** panel — top 5 skills by call count, with error count and average duration (ms)
- **Recent chat sessions** panel — last 5 conversations with first user message preview and message count
- Dark-mode theme: all KPI/feature/panel/dashboard/widget cards use `--admin-surface` / `--admin-border` / `--admin-text` glass tokens to match the rest of the admin shell (no more white cards on dark background)
- Manual Refresh button + "Updated HH:MM:SS" indicator
- Backend endpoint: `GET /admin/api/overview/stats` aggregates from `page_views`, `form_submissions`, `chat_conversations`, `chat_messages`, `orders`, `skill_usage_log`, `agent_skills`, `presentations`, `agent_provider_settings`. Each Phase A block is wrapped in try/except so a missing table never breaks the load

### Custom Dashboards Builder
- Admin → Custom Dashboards tab — create your own boards with cards and charts
- Three data source types per widget:
  1. **Built-in metric** — visitors, page views, leads, chats, visitors-by-day, top pages, recent leads
  2. **External Postgres** — paste a connection URL once, then write SELECT queries
  3. **REST API** — paste base URL + optional headers (e.g. Authorization), then per-widget path + value path
- Four widget types: KPI (big number), Line chart, Bar chart, Table
- External credentials are encrypted at rest with Fernet (key derived from `FLASK_SECRET_KEY`)
- External Postgres safety: SELECT/WITH only, comments stripped before regex check, multi-statement blocked, **opened in a read-only Postgres session** (engine-enforced), 5s statement timeout, 500-row cap
- Tables added: `external_data_connections`, `dashboards`, `dashboard_widgets` (cascade delete)
- All endpoints under `/admin/api/dashboards/*` and `/admin/api/external-connections/*` are admin-gated

### Theme / Color Editor
- Admin → Theme tab with color pickers + text inputs for: background, section 1, section 2, accent, text, glass border, glass background
- Font dropdowns for heading (serif) and body (sans-serif) with 12+ Google Fonts each
- Theme is fetched by the public site on load via `GET /api/theme` and applied as CSS custom properties
- Selected Google Fonts are dynamically loaded via `<link>` tag injection
- "Reset to Default" button clears all theme overrides

### Messaging (Email & SMS Campaigns)
- Admin sidebar group "Messaging" with three tabs: **Subscribers**, **Templates**, **Campaigns**
- **Subscribers**: manual add/edit, CSV import (`email`, `phone`, `name` columns; extras become merge tags), import-from-form-submissions, per-channel opt-in flags, signed unsubscribe URLs
- **Templates**: email or SMS bodies with `{{first_name}}`, `{{full_name}}`, `{{email}}`, `{{phone}}`, `{{unsubscribe_url}}` merge tags; AI drafting from a short prompt or by summarizing recent chatbot themes; per-template preview and "test send to me"
- **Campaigns**: pick a template, target all/list/specific IDs, send immediately or schedule for a future time; per-recipient log with delivery / failure status
- **Providers**: Email via Resend (Replit Connector preferred, falls back to `RESEND_API_KEY` + `RESEND_FROM_EMAIL` env vars). SMS via Twilio (env-only — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` — no Replit connector available)
- **Scheduler**: in-process background thread (`messaging.start_scheduler`) ticks every 30 s, picking up `messaging_campaigns` rows whose `send_at <= NOW()` and dispatching them; immediate sends skip the wait by kicking the dispatcher thread directly
- **Webhooks**: `/webhooks/resend` (Svix-signed when `RESEND_WEBHOOK_SECRET` is set, fail-open otherwise); `/webhooks/twilio/sms-status` and `/webhooks/twilio/inbound-sms` (HMAC verified against `TWILIO_AUTH_TOKEN`; STOP/UNSTOP keywords mirror opt-out)
- **Unsubscribe**: `/unsubscribe?token=…` flips `opt_in=false` on the subscriber; tokens are HMAC-signed with `FLASK_SECRET_KEY`
- **Database tables**: `subscribers`, `messaging_templates`, `messaging_campaigns`, `messaging_log`
- **Module**: provider clients, scheduler, signing, and CSV parsing live in `messaging.py`; admin routes and AI drafting live in `app.py`

### Automations (no-code "if X then Y" workflows)
- Admin sidebar group "Automation" with one tab: **Automations** (list + editor + run-log all in one)
- **Triggers**: `form_submitted` (any form or specific slug), `new_chat` (first message of a conversation), `schedule` (interval minutes or daily HH:MM UTC), `webhook` (POST any JSON to `/automations/hook/<token>`), `manual` (run from the editor only)
- **Actions** (run in order): `send_email`, `send_sms` (use messaging.py's providers and templates), `ai_draft` (OpenAI chat completion, model defaults to `gpt-4o-mini`), `http_request` (GET/POST/PUT/PATCH/DELETE with optional headers and JSON body, 15s timeout), `save_to_table` (insert into any non-blocklisted table via the existing internal-DB helpers), `delay` (1–300 seconds), `condition` (branch — short-circuits the rest of the run when its rule tree is false), `call_skill` (invoke ANY enabled chat skill, MCP tool, or custom skill by `skill_name` with a merge-tag-rendered JSON args object; result captured under `output_key` so later steps can `{{step_X.<output_key>.field}}` it)
- **Dynamic action surface**: `call_skill` resolves at runtime through a hook (`automations.set_skill_executor` wired to `_execute_chat_tool_inner` in `app.py`) so every newly-added MCP tool / custom webhook skill / custom SQL skill becomes available to automations the instant it's enabled — no code changes, no restart. The `/admin/api/automations/metadata` endpoint returns a `skills` catalogue (`name`, `display_name`, `description`, `category`, `source` ∈ {builtin, mcp, webhook, sql, knowledge, custom}, `server_name`, `args_schema`) which the editor uses to render a progressive-disclosure picker.
- **Action picker UI** (`templates/admin/dashboard.html`): the "+ Add step" button opens a modal with two tiers — a **Common actions** grid for the seven hard-coded kinds always visible, plus a collapsed **Skills & integrations** accordion with a count badge (e.g. "65 available — including 47 from connected services"). Expanding reveals a search box and category-grouped tiles. Selecting a skill creates a `call_skill` step pre-filled with `skill_name` and an args JSON template generated from the skill's `args_schema` (one key per property, type-appropriate placeholder).
- **Admin Assist AI tools**: read tools (`admin_list_automations`, `admin_get_automation`) run immediately; write tools (`admin_propose_create_automation`, `admin_propose_update_automation`, `admin_propose_toggle_automation`, `admin_propose_delete_automation`) go through the standard Propose → Approve flow via `admin_pending_actions` and dispatch through `_admin_execute_automation_pending` (validates trigger_type ∈ TRIGGER_TYPES, every step `kind` ∈ ACTION_TYPES, every `call_skill` step's `skill_name` exists in `agent_skills`-enabled). The generic `admin_propose_insert/update/delete` and `admin_propose_run_sql` tools refuse to touch `automations` / `automation_runs` / `automation_versions` / `automation_settings` / `automation_webhook_rejections` (mirrors the MCP pattern via `ADMIN_DEDICATED_WRITE_TABLES`) so the AI is forced through the dedicated tools.
- **Branching**: a dedicated `condition` action gates the rest of the run, and every step also accepts an optional per-step `when` filter. Both accept either a single leaf `{field, operator, value}` OR a `{combinator: 'AND' | 'OR', rules: [<node>, ...]}` group with arbitrarily nested sub-groups (max depth 5, max 50 leaves total) so admins can express logic like "plan is Premium AND country is US" or "(failed AND retries > 3) OR escalated" without code. The evaluator short-circuits AND on the first false / OR on the first true, and run-log skip reasons surface the exact sub-rule(s) that caused the skip. Operator catalogue (`eq`, `neq`, `contains`, `not_contains`, `starts_with`, `ends_with`, `blank`, `not_blank`, `gt`, `gte`, `lt`, `lte`) is shared between both — numbers compared numerically, everything else as strings. The dashboard renders a recursive AND/OR rule-builder for any action whose metadata sets `config_ui: 'rule_builder'` (today: `condition`) and for the per-step `when` filter; merge tags work inside every `field` / `value`
- **Merge tags**: every config field is rendered with `{{trigger.fields.email}}`, `{{step1.text}}`, `{{step_my_step_name.status}}` style placeholders before the action runs; renderer recurses into nested dicts/lists
- **Engine**: `automations.py` registers a tick callback with `messaging.py`'s 30s scheduler — no extra threads. Per-run worker thread, `120 s` overall timeout, max 5 concurrent runs (semaphore), 60 runs/hour/automation rate limit
- **Run log**: every dispatch creates an `automation_runs` row with `status` (queued/running/succeeded/failed/timeout), `step_results` JSONB (one entry per step with config-rendered, output, ok flag, elapsed_ms), `is_dry_run` flag, and `triggered_by` source. Visible in the editor with re-run button
- **Retention**: a daily cleanup tick (registered against the messaging scheduler) deletes `automation_runs` older than the effective retention horizon, but always keeps the most recent N rows per automation regardless of age — so a low-volume automation never loses its full history, and a webhook firing at the 60/hour cap can't accumulate ~525k rows/year. The two knobs (`retention_days`, `keep_recent_per_automation`) are admin-tunable from the **Run history retention** panel on the Automations tab; saves write to a singleton `automation_settings` row (id=1) which `_cleanup_runs_tick()` re-reads on every pass via `_effective_retention()`, so changes take effect on the next tick without a restart. The env vars `AUTOMATIONS_RETENTION_DAYS` (default 30) and `AUTOMATIONS_RETENTION_KEEP_RECENT` (default 100) remain the *fallback* defaults whenever a DB column is NULL, preserving prior behaviour for installs that never visit the panel. UI inputs and the PUT `/admin/api/automations/settings` route both clamp into safe bounds (1–3650 days; 0–100k keep-recent). Cleanup cadence is still governed by `AUTOMATIONS_RETENTION_TICK_SECONDS` (default 86400 = 1 day, env-only) and on DB errors the cooldown is reset so the next tick retries. Composite index `idx_runs_automation_queued` on `(automation_id, queued_at DESC)` keeps both the cleanup window-function scan and the editor's "recent runs" panel fast as the table grows. Current effective values + per-field "default vs custom" flags are surfaced in `automations.status_summary()` under the `retention` key and rendered into the Automations status banner.
- **Test runs**: editor has a "Run now" panel that fires the automation with admin-supplied JSON sample data and polls the run row until it finishes; "dry-run" checkbox flags the row in the log (actions still execute for real)
- **Webhook security**: tokens are 32-char URL-safe random; a partial unique index covers only non-null tokens; `/automations/hook/<token>` only fires when `enabled=TRUE` and `trigger_type='webhook'`
- **Versioning**: every meaningful save (create / update / restore) appends a snapshot to `automation_versions` (`name`, `description`, `trigger_type`, `trigger_config`, `action_steps`); identical-content saves are de-duped so the history stays useful. The editor has a "Version history" button that opens a modal listing every saved version with a one-click "Restore" — the restored copy keeps the live on/off setting and is itself written as a new version, so no history is ever lost. Schema-drift safety: a restored snapshot is re-validated against the current trigger and action catalogues, so versions referencing a removed action kind fail cleanly with 422.
- **Import / export (cross-site sharing)**: per-row "Export" button downloads a self-contained JSON file (`schema: "automation/v1"`); list-view "Import" button uploads any such file (256 KB cap) and creates a new automation. Imports are forced to `enabled=FALSE` so the admin can review credentials, table refs, and webhook URLs before turning it on; webhook tokens are always re-minted on import; name collisions get an `(imported N)` suffix
- **Database tables**: `automations`, `automation_runs`, `automation_versions`, `automation_settings`, `automation_webhook_rejections`
- **Module**: engine, registry, dispatch, rate-limit, and scheduler tick live in `automations.py`; admin routes (CRUD + versions + import/export) and the public webhook live in `app.py`

## MCP Connectors (Model Context Protocol)

Lets the owner plug remote MCP servers in as callable tools for either the admin assistant only, or also for the visitor-facing chat agent (Velo). Built on the same approve/reject card flow as every other admin write.

- **Schema**: `mcp_servers` (one row per remote server: `name`, `url`, `transport` http/sse, `auth_type` none/bearer/header/oauth, `auth_credential`, `enabled`, `allowed_for_admin` default TRUE, `allowed_for_velo` default FALSE, `connector_type` default 'custom', `last_test_*` audit fields) + `mcp_tools_cache` (cached `tool_name` + JSON Schema per server, refreshed on demand). Both tables created via raw psycopg2 `CREATE TABLE IF NOT EXISTS` in `init_db`, SERIAL primary keys, no Drizzle. `mcp_tools_cache.server_id` cascades on delete.
- **Client**: `_mcp_post`/`_mcp_initialize`/`_mcp_list_tools`/`_mcp_call_tool` in `app.py` speak JSON-RPC 2.0 over Streamable HTTP **and SSE**, accept both `application/json` and the first `text/event-stream` data event, and reuse the existing `_webhook_url_safe` validator + DNS pin patch so the SSRF block (localhost / private IPs / link-local) applies to MCP URLs too. **OAuth (Authorization Code + PKCE S256)** is fully wired: `_mcp_oauth_*` helpers handle PKCE pair generation, state-token persistence in `oauth_state` JSONB, token exchange (`_mcp_oauth_exchange_code`), and transparent refresh (`_mcp_oauth_get_valid_access_token`, 60s leeway) — `_mcp_auth_headers` injects `Authorization: Bearer <access_token>` automatically. The token-exchange POST goes through `_mcp_oauth_safe_post` which DNS-pins the resolved IP and forbids redirects (defends against private-IP/redirect-rebind attacks).
- **REST endpoints (admin-only)**: `GET/POST /admin/api/mcp/servers`, `PUT/DELETE /admin/api/mcp/servers/<id>`, `POST /admin/api/mcp/servers/<id>/test`, `POST /admin/api/mcp/servers/<id>/refresh-tools`, `GET /admin/api/mcp/servers/<id>/tools`, `GET /admin/api/mcp/connector-blueprints`. Every mutating route snapshots into `admin_setting_snapshots` and re-runs `sync_custom_skills_to_agent_skills()`, so changes are live without restart.
- **Tool routing**: `sync_custom_skills_to_agent_skills()` mirrors every cached MCP tool whose server is `enabled=TRUE` into `agent_skills` as a row named `mcp__<server_slug>__<tool_slug>` with `category='mcp'` and `config_json={"type":"mcp","server_id":N,"tool":"…"}`. Stale rows are pruned on each sync. The dispatcher's `_CUSTOM_SKILL_EXECUTORS["mcp"]` handler (`_exec_custom_mcp`) loads the server row and calls `_mcp_call_tool`. `get_active_chat_tools(audience='velo')` filters MCP rows to only those whose server has `allowed_for_velo=TRUE`; `audience='admin'` mirrors that with `allowed_for_admin=TRUE`.
- **Velo gating**: per-server toggle, default OFF. Adding a new server never exposes it to the visitor chat until the owner explicitly flips Velo on (either from the dashboard tab or by asking the admin assistant). The admin chat system prompt instructs the model never to propose toggling Velo on without an explicit ask.
- **Dashboard tab**: under the AI & Chat sidebar group — list of servers with status pill, enabled/Velo toggles, edit/delete; add-server form (transport, url, auth_type, header name when applicable, credential, description); per-server expandable cached tool list; Test and Refresh-Tools buttons.
- **Admin assistant tools**: read = `admin_mcp_list_servers`, `admin_mcp_test_server`, `admin_mcp_refresh_tools` (run immediately, no approval). Approval-gated proposers = `admin_mcp_propose_add_server`, `admin_mcp_propose_update_server`, `admin_mcp_propose_toggle_velo`, `admin_mcp_propose_toggle_enabled`, `admin_mcp_propose_remove_server` — all return `awaiting_approval=true` and create a row in `admin_pending_actions` that the owner approves/rejects in the chat UI. The chat loop also dynamically injects every admin-allowed `mcp__*` tool each round, so newly-added MCP tools become callable from chat without restart.
- **MCP V2 (April 2026)**: SSE transport and OAuth (Authorization Code + PKCE S256) are now first-class. Admin can mark a server `auth_type='oauth'` with `oauth_state.{client_id, client_secret?, auth_url, token_url, scopes[]}` and click **Connect via OAuth** — the popup hits `POST /admin/api/mcp/servers/<id>/oauth/start` to get the authorize URL, the provider redirects to `GET /admin/oauth/mcp/callback?code=&state=` which validates the state with `hmac.compare_digest` (600s TTL), exchanges the code, and posts `{type:'mcp_oauth_done'}` back to the opener so the dashboard refreshes. **Disconnect** wipes only the token fields (preserves client_id/url config). Both propose-add and propose-update tools call `_admin_validate_mcp_server_fields` BEFORE creating the pending action so bad URL / unsupported transport / missing OAuth fields are rejected with the same wording the execute path uses. PUT shallow-merges `oauth_state` so admin re-saves never clobber live tokens.
- **MCP V2 — secret-leak hardening (architect re-review fixes)**: (1) `_exec_custom_sql` (custom SQL skill executor used by chat tool calls) was bypassing the secret-table denylist — now applies `_admin_sql_secret_table_check` + `_admin_sql_banned_identifier_check` and `_redact_recursive` on returned rows, so a custom SQL skill can no longer SELECT raw `mcp_servers.oauth_state` (tokens). (2) `_exec_custom_mcp` / `_admin_tool_mcp_test_server` / `_admin_tool_mcp_refresh_tools` now SELECT `oauth_state` so the transport guard sees the connected token (otherwise OAuth servers appeared "not connected" in chat). (3) `admin_snapshot_detail` and `admin_chat_action_get` now apply `_redact_recursive` so raw `snapshot_json` / `payload_json` / `result_json` can't surface MCP OAuth `access_token` / `refresh_token` / `client_secret` to the admin browser. The `_REDACTED_KEY_NAMES_LOWER` set already covers `client_secret`, `access_token`, `refresh_token`, `code_verifier`.
- **Security boundary**: credentials are never returned by `GET /admin/api/mcp/servers` (only an `auth_credential_set` boolean). The system prompt instructs the assistant to never echo credentials back. SSRF block is enforced for both admin-supplied URLs and the runtime tool calls.

## VELO Master AI Integration (Phase 2 + Phase 3 — April 2026)

Two-way bridge between this Flask install and an external **VELO Master** FastAPI service that owns cross-client orchestration. Built per a user-supplied spec and adapted to this codebase's actual schema (raw psycopg2, real table names, existing tenant_features system).

- **Files**: `velo_client.py` (outbound HTTP client, `velo.discover()` / `velo.use_tool()` / `velo.report_event()`), `velo_endpoints.py` (Flask blueprint mounted at `/api/velo`, plus `@velo_command` decorator + handler registry), `velo_handlers.py` (real handler bodies wired to this app's data).
- **Inbound endpoints**: `POST /api/velo/command` accepts `{"command": "...", "params": {...}}` and routes to the registered handler; `GET /api/velo/status` returns the available command list + uptime. Single dynamic command endpoint per the spec — adding a capability is just writing a new `@velo_command` function.
- **Auth**: Bearer token `VELO_AGENT_KEY`. Empty key = auth disabled in dev (convenience), but **fails closed in production** (`REPLIT_DEPLOYMENT` set → unset key rejects every request) so a missing key on deploy can't accidentally expose `manage_features` / `update_faq` to the public.
- **Registered handlers (Phase 2)**: `get_analytics` (signups from customers, paid revenue from orders, page_views, chat_conversations bucketed by today/week/month/year), `get_system_status` (DB ping, table count, key counters incl. `velo_errors_24h` from the audit log, uptime), `manage_features` (get / set / bulk_set / `apply_plan` — wired to existing `tenant_features` table + `set_tenant_feature` helper, **not** a parallel `feature_flags` table), `get_plans` (returns real `_FEATURE_REGISTRY` grouped by solo/growth/enterprise tier), `get_faq` / `update_faq` (UPSERT against `faqs`), `get_users` (list of `customers`, this app's user-equivalent). Skipped for now: `send_email`, `get_subscriptions`, `send_chat_message`, `manage_user`, `escalate_response`, `get_visitor_sessions`, `update_content`.
- **Audit log**: every command (success or failure) is written to `velo_audit_log` (`id SERIAL`, `command`, `params JSONB`, `status`, `result_summary`, `error_msg`, `actor`, `created_at`) with two indexes. Audit-write failures are deliberately swallowed so a missing/broken audit table can never block command execution.
- **Master registration**: `register_with_velo()` posts the full capability list to `{VELO_MASTER_URL}/api/agent-register` for two agent_ids (`admin_ai` + `visitor_ai`, both pointing at the same `/api/velo/command` endpoint). Triggered via the existing `@app.before_request` one-shot pattern (mirrors the messaging scheduler) so it fires exactly once per worker on the first served request — never blocks boot, never runs in the Flask reloader's parent process. Daemon thread, 5s timeout per call, `raise_for_status()` so 401/500 from master surfaces as a failure instead of a fake "registered" log line.
- **Env vars**: `VELO_MASTER_URL` (e.g. `http://localhost:8000`), `VELO_AGENT_KEY` (shared bearer token), `SITE_URL` (this install's public URL VELO will call back to; defaults to `http://localhost:5000`). When `VELO_MASTER_URL` is unset, registration logs `[velo] VELO_MASTER_URL not set — skipping` and the handler endpoints still work for direct testing.
- **Param hardening**: handler bodies use a `_safe_int(v, default, lo, hi)` helper for all integer coercion (limit, sort_order, faq id) so a malformed VELO param returns a clean error payload instead of a 500.
- **Boot timing**: `VELO_APP_START_TIME = _time.time()` captured at module import (top of app.py) so `/api/velo/status` reports uptime correctly under both `python app.py` and gunicorn workers.

### Phase 3 — full surface (April 2026, follow-up)

- **30 commands total** (was 7 in Phase 2). New: `get_subscriptions`, `get_visitor_sessions`, `get_chat_history`, `get_content` (generic listing across blog/events/products/services/testimonials/team/gallery/video/podcast/pages — single handler, `type` param keys into `_CONTENT_TABLES` whitelist), `get_orders`, `get_audit_log`, `get_settings` (singleton config rows: site/business_info/chatbot/voice/sphere — single handler, `key` param keys into `_SETTINGS_TABLES` whitelist), `get_costs`, `get_form_submissions`, `get_voice_logs`, `get_skills`, `get_mcp_servers`, plus writes `update_content` / `update_settings` / `manage_user` / `send_chat_message` / `toggle_skill`, plus gated `send_email` / `send_sms` / `trigger_weekly_digest` / `manage_plan` / `delete_content` / `refund_order`. Generic content/settings handlers replace ~10 near-identical per-table handlers — one source of truth for column safelisting.
- **Per-table search column map**: `_CONTENT_TABLES` carries `(table, slug_col, search_cols)` per content type. `get_content`'s `search` param ILIKEs only against the columns each table actually has (testimonials → `reviewer_name, content`; team → `name, role, bio`; blog → `title, excerpt`; etc.) so a search on testimonials no longer errors with "column 'title' does not exist".
- **`update_content` column safelist**: queries `information_schema.columns` for the live column list, drops `id/created_at/updated_at`, intersects with the caller's `fields` dict, parameterizes everything with `%s`. Rejected columns are echoed back so master can fix its call. Table name comes from the trusted `_CONTENT_TABLES` whitelist (not the user's input).
- **`update_settings` JSONB coercion**: `business_hours` and `social_links` are JSONB columns — the handler auto-serializes dict/list values with `json.dumps` and casts with `%s::jsonb` so callers can send native objects.
- **Confirmation gate (`requires_confirmation=True` on the `@velo_command` decorator)**: 6 destructive/outbound handlers opt in. First call returns `{status:"confirmation_required", confirm_token, preview_params, expires_in_seconds:120}` without executing. Token is HMAC-SHA256 over `command|sorted_params_minus_confirm_token|time_bucket` keyed on `VELO_AGENT_KEY`. Verify accepts current OR previous bucket → 60–120s effective lifetime. **Single-use enforcement**: a successful verify also calls `_consume_confirm_token` which records the token in `_USED_CONFIRM_TOKENS` (in-memory dict, lock-protected, opportunistically evicted on insert) so a master-side retry loop can't fire the same `send_email` twice from one token.
- **Stripe in `refund_order`**: prefers `stripe_client.get_stripe()` (the repo's resolver that picks up the Replit Stripe connector token) before falling back to bare `import stripe`. Without this, refunds 401 in connector setups even when the storefront's checkout works.
- **Dynamic re-registration**: `POST /api/velo/refresh-registration` re-runs `register_with_velo(force=True)`, returns `{forced, client_registered, agents{...}, capability_count, site_url, command_count, commands[...]}`. `register_with_velo` now accepts a `force` kwarg and returns its result dict so this endpoint can echo what happened. Use case: enable a new feature group → call refresh → master sees the expanded capability list without restarting the worker.
- **`/api/velo/status` extras**: now includes `command_count` and `gated_commands` (sorted list of which commands require the confirmation flow) so master can render a UI hint without enumerating descriptions.

## Onboarding & Deployment (Tier 0 — April 2026)

First slice of the multi-tier client-onboarding work. Goal: any developer can clone this repo and stand up a fresh client install on any host (Replit, Render, Fly.io, Railway, plain VPS, Docker) without reverse-engineering the codebase. Tiers 1–4 (preflight script, VELO-driven provisioning, first-run wizard, snapshots/cloning) are scoped but not yet built.

- **Files added**: `.env.example` (full 22-var inventory with REQUIRED / STRONGLY RECOMMENDED / OPTIONAL labels and per-feature comments), `README.md` (human-facing quickstart — distinct from the agent-facing `replit.md`/`AGENT_KNOWLEDGE_BASE.md`/`GUIDE.md`), `requirements.in` (mirror of `pyproject.toml` deps for non-uv tooling — Docker, buildpacks; uses `.in` extension because the system protects `requirements.txt`), `Dockerfile` (Python 3.11-slim base, `libreoffice-impress` + `libreoffice-core` for the PPT export pipeline, gunicorn entrypoint with `WEB_CONCURRENCY` knob, `/healthz` HEALTHCHECK), `docker-compose.yml` (one-command local spin-up: app + Postgres 16-alpine + persistent `uploads` volume, DB exposed on host port 55432 for direct psql access), `DEPLOY.md` (per-platform recipes for Replit / Render / Fly.io / Railway / plain VPS Ubuntu + Docker, including systemd unit + nginx reverse-proxy + certbot snippets for the VPS path).
- **Replit-isms made portable** (env-var swaps, both names accepted so Replit keeps working):
  - `_public_base_url()` (used by unsubscribe / webhook / SEO canonical links): now prefers `PUBLIC_BASE_URL` over `REPLIT_DOMAINS`. Falls through to `request.host_url` as before.
  - `_resolve_velo_callback_url()` (the URL VELO Master calls back to): priority is now `SITE_URL` → `PUBLIC_BASE_URL` → `REPLIT_DOMAINS` → localhost fallback. All three honor the same localhost-guard so master never gets handed an unreachable URL.
  - `SESSION_COOKIE_SECURE`: now flips on if either `FORCE_SECURE_COOKIES=1` (explicit, host-agnostic) OR `REPLIT_DEPLOYMENT=1` (Replit-auto) is set.
- **ADMIN_PASSWORD footgun guard**: app boots with `ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")` unchanged (back-compat for existing installs), but now prints a loud `WARNING: ADMIN_PASSWORD is at the default value 'admin'...` to stderr at module import if the default is in effect. Visible in any deploy log; doesn't block boot.
- **Things deliberately NOT changed in Tier 0**: `messaging.py` and `stripe_client.py` still use `REPLIT_DEPLOYMENT` to pick prod-vs-dev for the Replit connector lookup — those code paths only run when a `REPL_IDENTITY` token exists (i.e. on Replit), so the env-var name is correct as-is. The `stripe-replit-sync` Node dep in `package.json` is a Replit-only convenience and is not imported by any Python runtime code; it's documented as safe-to-leave in `DEPLOY.md` (file protection blocked direct removal). The `latent NameError on sys` in scraper progress logging is fixed as a side effect — `sys` is now imported at module top, so those error paths no longer silently NameError.
- **`.gitignore` rewritten**: added Python (`__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`), env-secrets (`.env`, `.env.*` with `!.env.example` allowlist, `.flask_secret`), build artifacts, OS/editor files, and the `uploads/` directory (should be a persistent volume, not a git tree). Old entries (`server/public`, `vite.config.ts.*`) preserved under a "legacy" comment in case some other tooling relies on them.
- **Verification**: workflow restarted clean. Boot log shows the new `WARNING: ADMIN_PASSWORD...` line, then the existing VELO registration sequence (`30 capabilities`, both `admin_ai` + `visitor_ai` agents registered against the cloudflare callback URL). All public `/api/*` endpoints return 200 on the smoke test. `app.py` AST-parses cleanly.

## VELO-Driven Provisioning (Tier 2 — April 2026)

Second slice of the onboarding work. Goal: a freshly-deployed install can be brought to a working baseline (settings + features + FAQs + admin user + optional starter content) in **one** master-side call, instead of 20+ chained `update_settings` / `update_faq` / `manage_features` round-trips. Built entirely as a composition layer over the Phase-3 single-purpose handlers; no schema changes, no new tables.

- **New handler `bootstrap_install`** (velo_handlers.py, end of file): `requires_confirmation=True`, takes `params.template` as a single dict. Calls existing handlers as plain Python functions (the `@velo_command` decorator returns `func` unchanged, so they're callable in-process without going back through HTTP). Capability count: 30 → 31. Gated commands list: 6 → 7.
- **Template shape** (top-level keys, all optional — omitted sections skipped silently):
  - `settings`: dict of `settings_key → fields_dict`. Keys are the `_SETTINGS_TABLES` whitelist entries (`site_settings`, `business_info`, `chatbot_settings`, `voice_settings`, `sphere_settings`). Each fields_dict is forwarded verbatim to `update_settings`, which already does column whitelisting + JSONB coercion (hours, social_links).
  - `features`: dict with EITHER `plan` (one of `solo` / `growth` / `enterprise`, applied via `manage_features apply_plan` — preferred path) OR `set` (dict of `feature_name → bool`, applied via `bulk_set`).
  - `faqs`: list of `{question, answer, sort_order}`. Deduped on question text via `SELECT id FROM faqs WHERE question = %s LIMIT 1` before insert, so re-runs increment `faqs_skipped_existing` instead of creating duplicate rows.
  - `admin_user`: dict with `email` + `name`. Calls `manage_user create`; that handler already returns `error: "...already exists..."` on duplicate email, which bootstrap detects and reports as `{existed: true, id: ...}` in the summary instead of treating as failure.
  - `content`: dict of `content_type → list_of_fields_dicts`. Content types match the `_CONTENT_TABLES` whitelist (`blog`, `events`, `products`, `services`, `testimonials`, `team`, `gallery`, `video`, `podcast`, `pages`). INSERT-only — callers should omit this block on re-runs unless they want additional rows. Each item goes through `update_content` which auto-discovers valid columns from `information_schema` and silently drops unknowns.
- **Idempotency contract**: settings (singleton UPDATE, no dupe risk), features (sets values, no dupe risk), FAQs (dedup-on-question), admin user (dedup-on-email by underlying handler) are all safely re-runnable. Only `content` is INSERT-only. The smoke test ran the same generic template twice — second run reported `faqs_created: 0`, `faqs_skipped_existing: 3`, `admin_user.existed: true`, `ok: true`.
- **Failure model**: per-section errors collected into `summary.*_errors` arrays, never raise. Single failing FAQ doesn't abort the bootstrap; `summary.ok` is `true` only when every error list is empty. This keeps partial bootstraps diagnosable from the master side instead of opaque 500s.
- **Starter templates** in `onboarding_templates/`:
  - `generic.json` — bare-minimum baseline (3 FAQs, hours/contact placeholders, growth plan, basic chatbot persona). Safe default when the operator hasn't picked an industry.
  - `restaurant.json` — single-location restaurant (6 FAQs covering reservations / dietary / parking / hours, voice-on settings, "Sofia" reservations concierge persona, `private-dining` + `catering` services).
  - These are reference data for master to either fetch or modify. They're not loaded by the install at runtime — bootstrap accepts the template object inline, so master can synthesize templates dynamically (industry classification → template merge → call) without needing the install to host them.
- **End-to-end smoke test** (against the live app via `/api/velo/command`): first call returned `confirmation_required` + `confirm_token` + `preview_params`. Second call with the token executed in one round-trip: 3 settings sections applied (16 columns, 0 rejected), 16 features applied via `apply_plan: growth`, 3 FAQs created, admin customer created with id=2. Re-run was correctly idempotent.

## First-Run Wizard (Tier 3 — April 2026)

Third slice of the onboarding work. Goal: a non-technical operator can stand up a fresh install end-to-end without ever opening a JSON file. Browser-based form at `/setup` that submits to `bootstrap_install` (Tier 2) server-side, so the operator gets the same one-call provisioning + idempotency + error-collection without touching the VELO surface.

- **New routes in app.py** (after `/healthz`, ~line 4205):
  - `GET /setup` — renders `templates/setup_wizard.html` with the list of available presets. Returns 404 if `_is_install_bootstrapped()` returns True.
  - `GET /setup/preset/<name>` — returns one of the `onboarding_templates/*.json` files as JSON for the wizard's industry-preset dropdown to pre-fill from. Same 404 gate as `/setup`. Path component is whitelisted to alphanumeric + `-_` to block traversal.
  - `POST /setup` — accepts `admin_password` + `template_json` form fields. Validates the password against `ADMIN_PASSWORD` (subject to the existing `_login_throttle` per-IP brute-force budget — same shared bucket as `/admin/login`, so guesses here count against the same 429 ceiling). On success, calls `bootstrap_install` directly as a Python function (bypasses the VELO HTTP confirmation gate; the form submit IS the confirmation). Returns `{ok, summary, redirect}` JSON, or `{error}` with 4xx on failure.
- **State detection — `_is_install_bootstrapped()`** (app.py, ~line 4230): single `SELECT site_name FROM site_settings WHERE id = 1`. Returns False (→ wizard available) iff `site_name` still equals the seed default `'My Site'`. The wizard always sets `site_name` (it's the one required field), so the gate naturally closes after first successful run. Fail-closed on DB error: returns True so a transient hiccup never accidentally re-opens the wizard on a configured production install.
- **Security model**:
  - Public-fresh-install hijack guard: the POST requires `ADMIN_PASSWORD`. Without it, anyone who finds `/setup` on a freshly-deployed public host could lock the install with their own values.
  - The GET endpoints are unauthenticated by design — they only serve a form and read-only preset JSON, and they're 404 once the install is bootstrapped.
  - `noindex, nofollow` meta on the wizard page so it never gets indexed even if briefly public.
  - Bypassing `requires_confirmation`: calling `bootstrap_install` directly as a Python function (rather than via the `/api/velo/command` endpoint) skips the HMAC confirm-token flow. This is correct because (a) the form submit is the operator's "yes do it" signal, and (b) the password gate is the actual auth boundary. Documented in the route comment so this isn't mistaken for a security oversight.
- **Wizard UX** (`templates/setup_wizard.html`, single-file page):
  - Collapsible-feeling sections: industry preset, business basics, contact, chatbot persona, plan tile picker (solo / growth / enterprise — visual selection, not a select element), starter FAQs (add/remove dynamically, seeded from preset), owner contact, password gate.
  - Industry preset dropdown calls `/setup/preset/<name>` and pre-fills every field via the `applyPreset()` JS helper — operator can then tweak.
  - Empty-string fields are stripped client-side so `update_settings` doesn't get blank values overwriting future sensible defaults.
  - All interactive elements have `data-testid` attributes following the project convention (`select-preset`, `input-site-name`, `plan-tile-growth`, `button-add-faq`, `button-submit-wizard`, etc.).
  - Dark theme matches `/admin/login` (DM Sans + Playfair Display, glassmorphism cards, blue/violet radial gradients) so it feels native to the existing admin surface.
- **What's deliberately minimal**: no multi-step navigation (single-page form scrolls naturally), no draft persistence (operator runs through it once), no field-level validation beyond `required` on `site_name` + `owner_email` + `admin_password` (server-side validation is the source of truth via `update_settings` column whitelisting).
- **Verification**: workflow restarts clean. `_is_install_bootstrapped()` flips correctly. Fresh `GET /setup` renders the form and lists 2 presets (generic, restaurant). `GET /setup/preset/restaurant` returns the JSON. POST with the right password and a built template runs `bootstrap_install` and returns `{ok:true, summary, redirect:"/admin/login"}`. Wrong password returns 401 and increments the throttle. Subsequent `GET /setup` returns 404.

### Tier 3 — Post-Review Hardening (April 2026)

Code review flagged three real issues with the initial Tier 3 implementation. All three fixed and re-verified before declaring Tier 3 done:

- **Sentinel-string gate replaced with a marker column.** Previously `_is_install_bootstrapped()` checked `site_name != 'My Site'`, which would have broken if an operator legitimately named their business "My Site" (the wizard would never close, leaving setup publicly reachable). Added `installation_bootstrapped_at TIMESTAMPTZ NULL` to `site_settings` via the existing boot-time `ALTER TABLE … ADD COLUMN IF NOT EXISTS` pattern (next to the theme columns at app.py:1474-1482). Helper now reads that column directly. Set to `NOW()` on success, reset to `NULL` on failure so retries work without manual SQL.
- **TOCTOU race on the bootstrap gate eliminated.** Two concurrent POSTs could both pass the pre-check before either ran `bootstrap_install`, causing duplicate side effects. Replaced the read-then-act with a single conditional UPDATE: `UPDATE site_settings SET installation_bootstrapped_at = NOW() WHERE id = 1 AND installation_bootstrapped_at IS NULL RETURNING id`. The first request gets a row back (proceeds); subsequent ones get nothing (return 409 "Setup is already in progress or has finished"). Verified with two concurrent `curl` POSTs — A returned 409, B returned 200, only B's site_name persisted.
- **Preset preservation: client-side build now overlays form on the full preset.** Previously `buildTemplate()` reconstructed a fresh object from visible form fields only, silently dropping every preset section the form doesn't expose (`business_hours`, `social_links`, `voice_settings`, `content.services`, etc.). Fixed by stashing the loaded preset in `currentPreset` JS variable and deep-cloning it as the base in `buildTemplate()`, then overlaying form-edited values on top. Empty form fields are treated as "user didn't touch this" → preset value preserved. End-to-end test on a clean DB now shows 4 settings sections applied (21 fields), 6 FAQs, 2 services — vs the previous 2 fields and 1 FAQ pre-fix.
- **Failure-rollback semantics**: any hard exception in `bootstrap_install` or any soft failure (`summary.ok == False` due to template_errors / settings_errors / etc.) now resets `installation_bootstrapped_at` to NULL so the operator can fix the form and retry without touching SQL. The 5xx/4xx response includes the full summary so the wizard UI can show exactly what failed.
- **Re-verification**: full restaurant preset POST on a truly fresh state (`TRUNCATE services, faqs; reset site_name`) returned `ok=true` with all 4 settings sections (site_settings 6 fields + business_info 5 fields including business_hours dict + chatbot_settings 5 fields + voice_settings 5 fields), 6 FAQs created, 2 services created, 16 features applied via apply_plan growth, zero errors across all four error buckets. Marker set, gate closed.

### Tier 3 — Second-Pass Review Hardening (April 2026)

A second code review on the post-fix state confirmed the three original fixes are correct and surfaced two remaining concerns. Both addressed:

- **Required-field server validation.** Browser form has `required` on site_name, but a crafted POST could bypass it and persist `site_name=""`, leaving the public site rendering a blank business name while the gate marker is set. Added explicit pre-claim guard in `POST /setup` that rejects missing/empty/whitespace-only `settings.site_settings.site_name` with HTTP 400 BEFORE any DB write or claim. Verified: empty string → 400, missing entirely → 400, `"   "` → 400, all leave `installation_bootstrapped_at = NULL` so retries work.
- **Rollback-failure now surfaced, not swallowed.** Previously a failed `_release_claim()` was caught with bare `except: pass` — meaning a transient DB error during the failure-rollback path could permanently lock setup. Refactored release into a `_release_claim()` helper that returns `(ok, error_str)`. Both error response paths (hard exception and soft summary failure) now include `rollback_failed: bool`, `rollback_error: str|None`, and `manual_recovery_sql` fields when rollback itself fails. Operator gets a one-line copy-paste recovery command (`UPDATE site_settings SET installation_bootstrapped_at = NULL WHERE id = 1;`) instead of a silent permanent lock.

**Documented limitation (out of Tier 3 scope)**: a worker process killed mid-bootstrap (after the atomic claim, before bootstrap_install returns) would leave the gate locked with no in-process rollback opportunity. Operator recovery is the same one-line UPDATE shown above. A TTL-based lease column would be the production-grade fix; deferred since process-kill mid-bootstrap is rare and the recovery is a single SQL command.

## Preflight Doctor Script (Tier 4 — April 2026)

Fourth slice of the onboarding work. Goal: an operator (or a CI pipeline) can verify a fresh install is healthy without poking through the admin UI or the boot log. Single Python file, no extra dependencies (just `psycopg2` which is already pulled in for the app).

- **File added**: `scripts/preflight.py` — standalone CLI, executable (`chmod +x`), runnable as `python scripts/preflight.py`. Adds project root to `sys.path` itself so it works from any cwd.
- **Categories of checks**:
  - **Required** (FAIL = exit 1): `DATABASE_URL` set + reachable + reports Postgres version; `ADMIN_PASSWORD` set + not equal to `'admin'`; at least one of `OPENAI_API_KEY` / `AI_INTEGRATIONS_OPENAI_API_KEY` / `ANTHROPIC_API_KEY`.
  - **Strongly recommended** (WARN): `FLASK_SECRET_KEY` (set as env or `.flask_secret` file present — WARN-not-FAIL because the app self-generates a random key on first boot, but missing it means sessions invalidate every restart); `SITE_URL`/`PUBLIC_BASE_URL` (or Replit-managed `REPLIT_DOMAINS`); `ADMIN_EMAIL`.
  - **Schema & install state** (mix of OK/WARN/FAIL, each DB probe independently exception-safe): table count from `information_schema.tables` (expects ~80+, FAIL on 0, WARN on partial); Tier 3 wizard marker (`installation_bootstrapped_at` NULL → WARN with hint to visit `/setup`); customer row count (info-only — note this app's auth model is single-password ADMIN_PASSWORD, NOT a per-user `is_admin` flag, so the customers count is just a useful signal for "did the wizard's `manage_user` call run").
  - **Optional integrations** (INFO/WARN, never FAIL): grouped checks for Resend (API key + from-email), Twilio (SID + token + from-number), Stripe (secret + webhook secret), ElevenLabs, Brave, Google Places, Yelp, TripAdvisor, Sentry, ADMIN_PHONE, VELO (master URL + agent key), Resend webhook secret. Each one labeled with the feature it enables (e.g. "outbound SMS", "Stripe checkout / storefront") so the operator can decide what's worth wiring.
  - **Replit-specific** (only shown when `REPL_IDENTITY` or `REPLIT_DOMAINS` is set): `REPL_IDENTITY`, `REPLIT_DOMAINS`, `REPLIT_DEPLOYMENT`. Skipped entirely off-Replit so the report stays clean for VPS/Docker deploys.
- **Output modes**:
  - Default: human-readable with ANSI colors when stdout is a TTY, plain text otherwise. Each check shows `[ OK ]` / `[WARN]` / `[FAIL]` / `[ -- ]` icons. Failures and warnings always show their detail/feature lines; OK results are terse unless `--verbose`.
  - `--json`: machine-readable, suitable for `jq` or CI gates. Each check is a `{name, status, message, feature, detail}` object plus a top-level `summary` with counts and a `healthy: bool`.
  - `--quiet`: only prints non-OK items (good for cron / monitoring jobs).
  - `--verbose`: shows feature/detail lines on OK results too.
  - `--strict`: warnings also exit non-zero (exit code 2 instead of 0).
  - `--no-color`: disables ANSI codes for log capture.
- **Exit codes**: `0` = all required green, `1` = any required failed, `2` = `--strict` mode hit a warning. Designed to slot into a deploy pipeline as a gate.
- **Verification**: ran the script in all 6 modes against the current dev DB. Default mode correctly reported 19 ok / 1 warn / 1 fail (FAIL on `ADMIN_PASSWORD='admin'`, WARN on install marker NULL since the wizard hasn't been run on this dev DB). `--json` produced valid parseable output. Exit code matrix: `[1 FAIL] → exit 1`, `[0 FAIL + 1 WARN] → exit 0`, `[0 FAIL + 1 WARN + --strict] → exit 2`. Wizard regression check: `/setup` still returns 200.
- **Docs wired**: `DEPLOY.md` post-deploy checklist now leads with "run `python scripts/preflight.py`" and lists the flags, exit codes, and what to do on the install-marker WARN. `README.md` quickstart gained step 5 (run preflight) before step 6 (visit `/setup`).
- **What's deliberately NOT in this script**: no `--init` flag (Tier 3 wizard supersedes interactive setup); no auto-fix actions (it's a doctor, not a surgeon — it tells you what's wrong, you decide); no live API ping for each integration (would take 10+ HTTP requests; checking key presence is the right scope for "did I configure things"). All three are reasonable follow-ups if the script grows.

## Snapshot & Clone Tool (Tier 5 — April 2026)

Fifth slice of the onboarding work. Goal: an agency that has dialled-in one client install can export its template-relevant state as JSON and use that JSON as the baseline for every subsequent client — same look, same FAQs, same persona, same plan, same starter content, no manual re-entry. Closes the loop with Tier 2 (`bootstrap_install`) and Tier 3 (`/setup` wizard) which both already accept this exact JSON shape on the import side.

- **File added**: `scripts/snapshot.py` — standalone CLI parallel in style to `scripts/preflight.py`. Adds project root to `sys.path` itself; opens a single read-only psycopg2 connection (`conn.set_session(readonly=True)` as a defence-in-depth so even a bug can't write); imports `_SETTINGS_TABLES` and `_CONTENT_TABLES` from `velo_handlers` so the column whitelists stay DRY (verified: those constants are importable without booting the Flask app — `velo_handlers` only imports `velo_endpoints` at module level, all `from app import …` calls are deferred inside function bodies).
- **What it exports** (top-level keys mirror `onboarding_templates/generic.json` exactly):
  - `$schema_version: 1` and `$description` (with timestamp + tenant_id) — metadata fields the existing presets already use.
  - `settings`: every singleton row from `_SETTINGS_TABLES` (`site_settings`, `business_info`, `chatbot_settings`, `voice_settings`, `sphere_settings`). For each key, only the safelisted columns from velo_handlers are read (so we can never accidentally export a column that `update_settings` would refuse on import). None-valued columns are dropped row-by-row so the target install gets preset defaults rather than explicit nulls.
  - `features`: emitted as `{"set": {feature_name: bool, …}}` rather than `{"plan": "..."}` because we can't reliably reverse-engineer which plan was applied (operator may have toggled individual flags after applying a plan); `set` captures the actual current state with zero ambiguity. Reads `tenant_features` for the configured tenant_id (default 1).
  - `faqs`: every row from `faqs` ordered by `(sort_order, id)`, projected to `{question, answer, sort_order}`. `bootstrap_install` already dedupes on question text on re-apply, so re-running is safe.
  - `admin_user`: opt-in via `--include-admin-user`. Picks the first customer (lowest id) as the admin proxy — this app's auth model is single-password (`ADMIN_PASSWORD` env var), there's no `customers.is_admin` flag, so ordinal priority is the only available signal. Default is OFF because admin identity is per-install-operator, not per-template.
  - `content`: opt-in via `--include-content[=types]` / `--include-all-content`. Reads each requested content type from its physical table per `_CONTENT_TABLES`, pulling the live column list from `information_schema.columns` so future schema additions are picked up automatically. Always strips `id` / `created_at` / `updated_at` so the target install's sequences and uniqueness constraints stay clean. None-valued columns dropped per row. Default content set when `--include-content` passed without value: `services` + `team` (the most template-y types — services describe what the business does and team profiles describe who runs it).
- **What it deliberately does NOT export**: customer rows, order rows, chat sessions, voice logs, audit log, form submissions, costs — all runtime data that should never be cloned across installs. Only the template shape (settings/features/faqs/optional content/optional admin) is captured.
- **CLI surface**:
  - `-o/--output FILE` — write to file instead of stdout
  - `--pretty` — 2-space indent (default: compact)
  - `--tenant-id N` — which tenant for features (default: 1)
  - `--include-content [TYPES]` — opt in to content (no value = defaults; comma list = explicit set)
  - `--include-all-content` — every content type (overrides --include-content)
  - `--no-content` — explicit opt-out (the default; flag wins over the others if combined)
  - `--include-admin-user` — include first customer's email/name
  - Output summary line on stderr (bytes / sections / row counts) so the JSON on stdout / in the file is never polluted; warnings on stderr too.
- **Exit codes**: `0` = clean snapshot, `1` = couldn't connect to DB (no JSON written), `2` = partial (some sections raised errors, but JSON was still written to stdout/file with the working sections — warnings on stderr).
- **Round-trip verification**: snapshot the live dev DB → save → POST through `/api/velo/command` to `bootstrap_install` (full two-step confirm-token flow). Result for the default-shape snapshot (settings + features + faqs + admin_user): `summary.ok: true`; all 5 settings sections accepted with **zero `rejected_columns`** (the snapshot's column shape exactly matches what `update_settings` accepts); all 16 features applied with `skipped_unknown: []` (every flag name is recognized); admin_user correctly resolved as existing (id=1). For the full-content shape (`--include-all-content`), see the `update_content` JSONB fix below.
- **Docs wired**: `DEPLOY.md` gained a "Cloning an existing install (snapshot → fresh deploy)" section between the post-deploy checklist and the legacy-Replit-isms notes — covers source-side commands, the API target-side flow, the per-section re-apply behavior (settings/features fully idempotent, faqs deduped on question text, content INSERT-style with UNIQUE-slug constraints causing duplicate-key errors on re-apply rather than silent dupes), and the exit code matrix. `README.md` quickstart gained a "Cloning a working install to a new client" sub-section right after the bootstrap-on-first-boot note.

**Code review fixes (post-architect-review)**:

- **JSONB round-trip fix in `velo_handlers.update_content`**: architect flagged that `update_content` (the function `bootstrap_install` calls per content row) didn't coerce dict/list values for JSONB columns the way `update_settings` already does, which would crash on `--include-all-content` snapshots that touched `gallery_cards.details`, `page_sections.settings`, or `products.gallery_images`. Fix: extended the `information_schema.columns` probe to also pull `data_type`, then in both the INSERT and UPDATE branches detect JSONB columns and emit `%s::jsonb` placeholders with `json.dumps(v)` values for dict/list inputs (other types go through unchanged so psycopg2's normal adaptation still handles them). Mirrors the exact pattern already used in `update_settings`. Verified with the round-trip test: full-content snapshot now applies cleanly with `summary.ok: true`.
- **Docs corrected on the wizard-paste flow**: original DEPLOY.md / README.md wording claimed an operator could paste snapshot JSON into the `/setup` wizard's "preset dropdown's custom option." That UI doesn't exist — the wizard only loads server-side presets (`/setup/preset/<name>`) and builds its `template_json` from form fields. Replaced with an API-only path; flagged the wizard JSON-upload tile as the intended future enhancement (Tier 5+).
- **Docs corrected on content re-apply behavior**: original wording said content was INSERT-only and "re-applying creates duplicates." That's wrong — 6 of the 10 content tables (`blog_posts`, `events`, `products`, `services`, `gallery_cards`, `page_sections`) have a `UNIQUE` constraint on `slug`, so re-apply errors with a duplicate-key violation rather than silently duplicating. DEPLOY.md now describes this accurately per section.
- **Exit-code docstring corrected**: the original snapshot.py docstring said exit `1` covers "DATABASE_URL not reachable, or required table missing." Implementation only returns `1` on a fatal connect failure — section-level errors (including missing tables) write a partial JSON and return `2`. Docstring now matches behavior.

## Admin-Side Snapshot/Clone (Tier 6 — April 2026)

Sixth slice of the onboarding work. Goal: extend the Tier 5 snapshot/clone pipeline to cover the **admin-side** state — agent skills, MCP servers, dashboards (with widgets), automations, messaging templates, model prices, the AI provider singleton, and the automation-policy singleton — so an agency that dials in a new skill on its master install can ship that change to every client install with one snapshot+replay round-trip. Tier 5 already handled customer-facing settings/FAQs/content; Tier 6 closes the loop on the agency's internal config that lives in the same DB.

- **Whitelist constants in `velo_handlers.py`**:
  - Two singletons (`agent_provider_settings`, `automation_settings`) added to the existing `_SETTINGS_TABLES` dict — DRY through `update_settings`, no parallel singleton machinery needed. They're flagged separately in `scripts/snapshot.py._ADMIN_SINGLETON_KEYS` so `read_settings` can route them to a separate output bucket and skip them entirely on the default snapshot (a customer-content snapshot must never quietly carry the agency's admin AI config).
  - New `_ADMIN_RECORD_TABLES` dict (parallel in shape to `_CONTENT_TABLES` and `_SETTINGS_TABLES`) defines each multi-row admin table by: `table` name, `key_cols` tuple (the natural key — `(name,)` for most; composite `(provider, model, surface)` for `model_prices`; `(name,)` for `dashboard_widgets` scoped under its `dashboard_id` FK), `sensitive_cols` set (redacted from snapshots without `--include-admin-secrets`), `drop_cols` set (always stripped — `id`, `created_at`, `updated_at`, `last_test_*`, `last_run_*`, `next_scheduled_at`, plus the FK column for children), and an optional `children` list for parent tables. Currently only `dashboards` has children (`dashboard_widgets`) but the schema generalises so future parent/child pairs can be added with one entry.
- **UPSERT helper `_upsert_admin_record(meta, row, parent_fk=None)`**: the core of "re-pushing the same snapshot updates clients in place instead of erroring on duplicates." Probes `information_schema.columns` for the table's live column set + JSONB types (mirrors the `update_content` pattern from Tier 5's post-architect fix), filters the supplied row dict to only known columns (silently drops unknowns rather than raising — old snapshots stay forward-compatible across schema additions), runs a SELECT-by-key, and either UPDATEs the matched row or INSERTs a new one. JSONB columns are bound through `%s::jsonb` casts with `json.dumps(v)` for dict/list values; everything else goes through psycopg2's normal adaptation. For child rows, `parent_fk` carries the freshly-resolved parent id forward so the child's FK column (stripped from the snapshot) is re-attached at insert time. Returns `("created" | "updated" | "error", id_or_error_string)` so the caller can roll up per-table counts.
- **`bootstrap_install` extension**: handles a new top-level `admin_records` block in the template payload. Iterates parent tables before pure-leaf tables (dashboards before everything else, since dashboards is currently the only parent — generalises automatically as more parents are added), pulls nested children off the parent row before the parent UPSERT (so they don't get mistakenly passed as parent columns), then loops the children list using the parent's resolved id. Per-table summary `{created, updated, skipped, errors[]}` lands in `summary["admin_records"][logical_key]`, with nested children getting their own `{created, updated, errors[]}` sub-block under the parent's table-summary. `summary["ok"]` now also requires zero per-table and per-child errors across the whole admin section.
- **`scripts/snapshot.py` extension**: two new flags — `--include-admin` (default OFF — opts in to both admin singletons in the `settings` block AND the multi-row `admin_records` block) and `--include-admin-secrets` (default OFF — keeps the sensitive columns; the CLI rejects this flag without `--include-admin` with exit 2 so a typo can't accidentally produce a credential-leaking snapshot file). New `read_admin_records` reader walks `_ADMIN_RECORD_TABLES`, projects via `information_schema.columns` minus drop_cols (and minus sensitive_cols unless secrets opt-in), reads parents first, then re-fetches each parent's id (the projected rows have id stripped) and pulls each child set scoped by FK; children are nested under the parent keyed by their `logical_key` ("widgets") rather than the physical table name. Summary line on stderr now includes total admin-record count (parents + nested) so the operator can confirm `--include-admin` actually picked something up.
- **What gets redacted by default**: `mcp_servers.auth_credential` and `mcp_servers.oauth_state` (OAuth tokens, basic-auth secrets), `custom_webhook_skills.headers_json` (often contains auth headers), `automations.webhook_token` (per-install secret used to authenticate inbound webhook calls). All require `--include-admin-secrets` to keep — verified by grep round-trip (default snapshot: 0 hits for known auth_credential value; with-secrets snapshot: 1 hit).
- **Round-trip verification**: seeded `dashboard_widgets` with one synthetic widget under the live "test" dashboard + set a probe `auth_credential` on `mcp_servers.velo_replit_test`. Snapshot with `--include-admin --include-admin-secrets` → mutated `custom_sql_skills.description` to a probe value, toggled `mcp_servers.enabled`, deleted the widget → re-applied snapshot via `/api/velo/command` `bootstrap_install` (full two-step confirm-token flow). Result: `summary.ok: true`; `agent_skills`: 65 updated, 0 errors; `custom_sql_skills`: 1 updated; `mcp_servers`: 3 updated; `automations`: 1 updated; `messaging_templates`: 1 updated; `model_prices`: 10 updated; `dashboards`: 1 updated with `widgets.created=1` (FK resolved correctly back to `dashboard_id=1` despite the FK column not being in the snapshot). Mutations all reverted; deleted widget recreated under the right parent; `auth_credential` restored to its probe value.
- **Docs wired**: `DEPLOY.md` "Cloning an existing install" section gained a "Cloning admin-side configuration (Tier 6)" sub-section covering the `--include-admin` / `--include-admin-secrets` commands, the per-table UPSERT-by-natural-key behaviour, the redaction defaults, and the always-stripped operational column list. `README.md` cloning sub-section gained a one-paragraph pointer to the admin-clone flow.

**Code review fixes (post-architect-review, Tier 6)**:

- **Blocking bug — `dashboard_widgets` composite key**: architect caught that the child UPSERT was matching on `("name",)` only, which would let two dashboards with same-named widgets ("Revenue", "Visits", etc.) silently overwrite each other on import. Fixed: `_ADMIN_RECORD_TABLES["dashboards"]["children"][0]["key_cols"]` is now `("dashboard_id", "name")`, and `dashboard_id` was removed from `drop_cols` so the FK reaches the WHERE clause. The existing `parent_fk` injection in `_upsert_admin_record` already adds the resolved `dashboard_id` to `fields` before the missing-keys check, so the new composite key is satisfied automatically — no change needed at the call site. Re-verified the round-trip (delete a widget, replay snapshot, widget re-created under the correct parent_id, 0 errors).
- **Determinism — `ORDER BY id ASC LIMIT 1`**: the SELECT inside `_upsert_admin_record` was using `LIMIT 1` without `ORDER BY`, so on a table with duplicate-name rows (`dashboards`, `automations`, `messaging_templates` — none have a UNIQUE constraint on `name`) the matched row was non-deterministic. Now `ORDER BY id ASC LIMIT 1` so "lowest-id wins" — the docs claim is now actually true. The same fix landed on the parent-id remap in `scripts/snapshot.py.read_admin_records` (uses `ORDER BY id ASC` + `dict.setdefault` so a duplicate-name parent doesn't overwrite the lowest-id entry in the lookup map). Both sides agree on which row is canonical.
- **NULL-safe key rejection**: `_upsert_admin_record` now explicitly errors out if any `key_cols` value is None (`null key column(s)` error). SQL's `WHERE col = NULL` never matches (NULL = NULL is NULL, not TRUE), so a NULL key would silently miss every row and INSERT instead of UPDATE. None of the current admin tables have nullable name columns, but the guard is there in case a malformed snapshot ever passes `{"name": None}`.
- **Explicit parent-id remap warning**: `read_admin_records` was silently `continue`-ing when a parent's id couldn't be resolved (theoretically impossible since parent_rows came from the same SELECT we just re-ran, but a real data-loss bug to debug if it ever fires). Now appends a `parent id remap miss for key=...` entry to the snapshot's `errors` list so it surfaces in the stderr WARN stream and bumps the exit code to 2.

## Pool + CSRF Hardening (Tier 7 — April 2026)

Seventh slice. Two production-grade hardening items that cost the operator nothing and remove two real risk surfaces: (1) Postgres connection pooling so the app stops opening a fresh socket on every single request, (2) CSRF protection on the admin surface so a malicious site cannot trick a logged-in operator's browser into mutating their install. Zero schema changes — both items are pure runtime middleware on top of the existing tables.

**Concrete changes:**

- **Process-wide Postgres pool (`app.py`)**: replaced the per-request `psycopg2.connect(DATABASE_URL)` body of `get_db()` with a `psycopg2.pool.ThreadedConnectionPool` borrow. Pool is created lazily on first call (so the test suite and `scripts/preflight.py` don't accidentally open sockets at import time) and is sized via `DB_POOL_MIN` (default 1) and `DB_POOL_MAX` (default 10) env vars. The borrowed connection is a `_PooledConnection` subclass of `psycopg2.extensions.connection` whose `.close()` returns the conn to the pool instead of closing it — that way every existing `try: ... finally: conn.close()` call site (and there are 100+ of them) works unchanged. The override resets `autocommit=True` and rolls back any open txn before putconn'ing, so a handler that crashed mid-`autocommit=False` can't poison the next borrower with a stale transaction. Falls back to a fresh direct `psycopg2.connect()` when the pool is exhausted (with a stderr warning) so traffic bursts above `DB_POOL_MAX` degrade gracefully rather than hard-failing.
- **Re-entrancy guard for the close override**: `ThreadedConnectionPool._putconn` itself calls `conn.close()` internally to discard a connection when the pool is already at `minconn` idle, when the conn is in `TRANSACTION_STATUS_UNKNOWN`, or when `putconn(close=True)` is requested. Without a guard, our overridden `.close()` would re-enter `pool.putconn(self)` from inside that internal close, recurse forever and deadlock the whole worker. The fix is a per-instance `_closing_directly` flag set inside the override's `try:` and cleared in `finally:` — when the pool's internal close fires, the override sees the flag and falls straight through to `super().close()`. Bug was caught by an isolation test that hung at `thread.join()` after 5 parallel requests.
- **Migrated 12 direct connect call sites**: every `conn = psycopg2.connect(DATABASE_URL); conn.autocommit = False` (the transactional pattern used by snapshot/install/preset routes) and every `conn = psycopg2.connect(DATABASE_URL)` (the autocommit pattern used by ad-hoc admin endpoints) now goes through `get_db()` so they pick up the pool. Three intentionally-untouched call sites remain (`automations.py:1175` uses a user-supplied `db_url`, and two routes around line 25741 / 25893 connect to *external* tester databases that the operator pasted into the form — they must NOT use the local pool).
- **Flask-side CSRF middleware (`app.py`, after `admin_logout`)**: per-session token via `secrets.token_urlsafe(32)` stored in `session["_csrf_token"]`. A `@app.before_request` hook validates `X-CSRF-Token` header (or `csrf_token` form field) on `POST/PUT/PATCH/DELETE` requests under `/admin/*`, using `secrets.compare_digest` for the equality check. Failures return `{"csrf_failed": true, "error": "..."}` with HTTP 403. Validation is skipped for: `/admin/login` and `/admin/logout` (the password is the credential; login CSRF is moot when an attacker who knows the password is already in), all public `/api/*` routes (anonymous; no session = no CSRF surface), VELO endpoints (Bearer-token auth), webhook endpoints (HMAC payload verification), and `/setup` (password-gated, install-once). Unauthenticated callers fall through to `@admin_required` so they see the standard 401-or-redirect rather than a confusing CSRF error.
- **Context processor + token endpoint**: `@app.context_processor _inject_csrf_token()` makes `csrf_token` available to every Jinja template without per-render plumbing — `templates/admin/dashboard.html`'s `<head>` now carries `<meta name="csrf-token" content="{{ csrf_token }}">`. A new `GET /admin/api/csrf-token` (admin_required, GET-only so the CSRF check itself doesn't apply) lets the dashboard SPA pick up a fresh token after a long idle without forcing a full page reload.
- **Front-end fetch wrapper (`templates/admin/dashboard.html`)**: a 30-line IIFE at the top of the first `<script>` block reads the meta tag, wraps `window.fetch`, and auto-injects `X-CSRF-Token` on every same-origin `/admin/*` POST/PUT/PATCH/DELETE. Existing `fetch()` call sites (276 of them in dashboard.html) need zero changes — the wrapper is transparent. On a 403 response with `{"csrf_failed": true}` the wrapper soft-reloads the page so the operator picks up a fresh token (handles the case where session expires mid-edit).
- **Smoke-test transcript**: pool — `/healthz` 200 in 3 ms, `/api/site-settings` 200 in 5 ms, 5 parallel public hits all 200 in 3-5 ms. CSRF — `POST /admin/api/chat/clear` without header returns 403 `csrf_failed`, with header but missing body returns 400 `session_id required` (validation reached past CSRF), with header and valid body returns 200 `ok: true` (full path: CSRF + admin_required + DB write via execute_db + connection returned to pool). Public endpoints (`/api/track/pageview`) unaffected.

## Test Suite (Tier 8 — April 2026)

Eighth slice. Stand up `pytest` and seed it with smoke tests around every customer-affecting path so future commits run against a baseline. Not unit tests — these don't pin down business logic. They ask the only question that matters at refactor time: "did this commit break a route the visitor or the operator relies on?" Run with `python -m pytest -q tests/`. Full suite is 37 tests, finishes in well under 10 seconds.

**What's covered (37 tests across 10 sections):**

- **Liveness + public marketing site (4)**: `GET /healthz` returns the literal `ok` body, `GET /` renders HTML, `GET /sitemap.xml` serves XML, `GET /robots.txt` serves a User-agent / Sitemap text body.
- **Public content APIs returning a JSON object (7, parametrized)**: `/api/site-settings`, `/api/business-info`, `/api/seo`, `/api/chatbot-settings`, `/api/voice/settings`, `/api/storefront-config`, `/api/sphere-settings`. Each must respond 200 and the top-level JSON body must be a `dict`.
- **Public content APIs returning a JSON list (13, parametrized)**: `/api/services`, `/api/events`, `/api/products`, `/api/blog`, `/api/faq`, `/api/team`, `/api/gallery-cards`, `/api/video-gallery`, `/api/podcast`, `/api/experiences`, `/api/pricing`, `/api/testimonials`, `/api/page-sections`. Each must respond 200 and the top-level JSON body must be a `list`.
- **Admin auth boundary (3)**: `/admin/login` GET serves a form-bearing HTML page; `/admin` redirects an anon caller to the login page (301/302); `POST /admin/api/chat/clear` from an anon caller is bounced with **302 or 401 only** (a 403 here would mean the CSRF middleware fired before `@admin_required` — a Tier 7 contract violation, so we deliberately exclude that code from the band).
- **CSRF protection (Tier 7 regression — 3)**: logged-in `POST /admin/api/chat/clear` without `X-CSRF-Token` returns 403 `{"csrf_failed": true}`; `GET /admin/api/csrf-token` returns a string token of sane length; the same POST with the token succeeds (200 `{"ok": true}`).
- **VELO surface (1)**: `GET /api/velo/status` mounts and responds (200/401/403 are all acceptable depending on whether `VELO_AGENT_KEY` is enforced on `/status`).
- **Route-mounting introspection (1)**: walks `app.url_map` directly and asserts `/api/chat` is registered with `POST` in its method set. We can't probe via HTTP because `/api/chat` doesn't validate the payload up front (an empty body still falls through to the rate-limit + cost-cap path) **and** the catch-all `@app.route("/<path:filename>")` near the bottom of `app.py` swallows any GET that no specific rule matched, so `GET /api/chat` returns 200, not 405. Pure introspection is the only safe probe.
- **POST validation paths (2)**: `POST /api/events/<bogus>/rsvp` and `POST /api/forms/<bogus>/submit` with empty body must return 400 or 404 — **not 405**, which would mean POST routing broke. We don't accept "any non-5xx" because that masks regressions where the route gets accidentally turned into GET-only.
- **Public detail pages (2, parametrized)**: `GET /blog/<bogus>` and `GET /event/<bogus>` must return exactly 404. Proves the slug-lookup path renders the not-found page rather than crashing on a missing row.
- **Setup wizard state (1)**: `GET /setup` returns 200 on a fresh install and 404 once `installation_bootstrapped_at` is set — both are correct behaviour and the test accepts either.

**Design decisions:**

- **In-process via Flask's `test_client`, not over the network**: tests boot the app once via `from app import app` (heavy: runs `init_db()`, starts background scheduler threads, imports `velo_handlers`, mounts the velo blueprint) and reuse it across the session. Each test gets a fresh `test_client()` so cookie / session state is isolated. No second port binds — these tests can run alongside the regular `python app.py` workflow without a port collision.
- **Read-only on the dev DB except for one bounded write**: every POST in the suite either authenticates with the real `ADMIN_PASSWORD` (only the CSRF-pass test, which **deliberately mutates one row** by clearing the chat history for the dummy session_id `smoke-csrf-pass` — that id is intentionally never used by real visitors) or sends a deliberately-invalid payload that exercises the validation path without writing real data (`__nonexistent_smoke_test__` slugs, empty bodies). No real visitor data is touched.
- **Skip-on-missing-creds, never fall back to `'admin'`**: the three CSRF tests that require an authenticated session call `pytest.skip(...)` if `ADMIN_PASSWORD` isn't set in the env. We do **not** default to `'admin'` because if the real password isn't `admin` the login silently fails and the "logged in but missing token → 403" test would pass for the wrong reason (the CSRF middleware skips for anon sessions).
- **Status-code bands ONLY where the right answer depends on environment config**: `/api/velo/status` returns 200 OR 401/403 depending on whether `VELO_AGENT_KEY` is set; `/setup` returns 200 OR 404 depending on bootstrap state. Everywhere else the assertion is tight (exactly 404, exactly 405-not-allowed via introspection, exactly 403 csrf_failed) so genuine regressions don't get masked.
- **Schedulers and background threads still run during tests**: importing `app` boots the messaging + automations schedulers a second time alongside the workflow process. For a smoke seed this is fine (daemons die with the pytest process) but it does mean two copies of every periodic job race during a `pytest` run. If a future scheduler job mutates DB rows on a tight interval this could become flaky — at that point either (a) gate scheduler startup behind an env var that pytest clears, or (b) stop the workflow before running the suite.

**Files added (3):**

- `tests/__init__.py` — empty package marker.
- `tests/conftest.py` — session-scoped `flask_app` fixture (one boot per pytest run) + per-test `client` fixture.
- `tests/test_smoke.py` — the 37-test smoke suite, organized by the section headers above.

**pyproject.toml**: a `[tool.pytest.ini_options]` block at the top sets `testpaths = ["tests"]`, `python_files = ["test_*.py"]`, and `addopts = "-q --strict-markers --tb=short"` so `pytest` picks the right directory and uses concise output without flags.

**Connection-pool footprint while tests run**: pytest's app instance opens its own `ThreadedConnectionPool(min=DB_POOL_MIN, max=DB_POOL_MAX)`, so when both processes are up the cluster sees ~2× the pool ceiling (≤20 conns at the defaults). Comfortable on the dev tier but worth knowing if a small-tier Postgres deploy hits `too many connections` — drop `DB_POOL_MAX` for the workflow, or stop the workflow before running the suite.

**How to extend:** when adding a new public route, append a one-liner to the relevant parametrized list in `tests/test_smoke.py` (no new function needed). When adding a new admin route, copy the CSRF-pass pattern (`_require_login(client)` → fetch `/admin/api/csrf-token` → POST with `X-CSRF-Token` header). When adding a route that's hard to probe over HTTP without side effects, copy the introspection pattern (`flask_app.url_map.iter_rules()`). Smoke tests stay shallow on purpose — anything that needs DB-state setup belongs in a separate `tests/test_<feature>.py` module with its own per-test transactional fixture.

## Object Storage (Tier 9 — April 2026)

Ninth slice. Every upload site in `app.py` previously wrote directly to `uploads/`, `uploads/voice/`, or `uploads/contracts/` on local disk. That's fine on a single-process dev box but fatal on every realistic deploy target — Replit's runtime FS is ephemeral, Heroku-style dynos rebuild on every release, Fly machines can be destroyed and recreated, and a multi-worker `gunicorn` behind a load balancer means worker A writes a file that worker B can't read back. Tier 9 introduces a thin storage abstraction that keeps the on-disk contract working by default while letting an operator flip a single env var to send all writes to AWS S3, Cloudflare R2, MinIO, or Wasabi without changing application code.

- **Module**: `storage.py` exposes `get_storage()` (singleton, lazy backend construction) returning an object with `write_bytes / write_fileobj / read_bytes / serve / exists / delete / size / url_for`. The Werkzeug-shaped `serve()` returns a Flask response that downstream `@app.route` handlers can return verbatim (200/206/304 negotiation handled by the backend, not the caller).
- **Backends**: `_LocalStorage` (default; identical to pre-Tier-9 disk behaviour, paths rooted at `<repo>/uploads/`) and `_S3Storage` (`boto3` client with optional `S3_ENDPOINT_URL` for non-AWS targets). `boto3` is imported lazily inside `_S3Storage.__init__` so installs that never enable S3 don't pay the import cost on boot.
- **Selection**: `UPLOADS_BACKEND=local` (default) or `s3`. The unset / empty / unknown case falls through to `local` so a misconfigured deploy fails into the safest possible state instead of 500ing every upload.
- **Subpath convention**: every call site uses a relative subpath — `<file>` (root, e.g. `9e8b16b913a264a4.jpeg`), `voice/<file>` (TTS cache MP3s), `contracts/<file>` (signed PDFs and templates). The local backend translates these to disk paths under `uploads/`; the S3 backend uses them as object keys directly. Subpaths are validated by `_check_safe_subpath` to refuse `..` traversal and absolute paths so a hostile input fails closed instead of escaping the upload root.
- **Legacy disk fallback**: `_S3Storage.read_bytes / serve / exists` catch `NoSuchKey` and `404` and re-dispatch to `_LocalStorage`. This means an operator can flip `UPLOADS_BACKEND=s3` immediately on cutover and all 595 pre-existing files keep serving from disk (read-only) while every new write lands in the bucket. A one-shot migration script that catches the legacy files up to the bucket is deferred to a follow-up task.
- **Streaming TTS redesign**: the old `_stream_tts_*` generators wrote to a per-request `tmp_path` on disk and atomic-renamed at end-of-stream. That doesn't translate to S3 (no atomic rename of object keys). The new design buffers chunks in an `io.BytesIO` while yielding to the client and uploads the whole MP3 in one `write_bytes` call when the stream completes cleanly. Cache write failures are explicitly logged but never break the user's playback — they already received the bytes in real time, and the next request just re-synthesizes from the provider.
- **Vision read-back security**: the deck-import vision path resolves `/uploads/<file>` URLs to bytes for base64 → LLM. The original code used `os.path.realpath` to confirm the file lived inside `UPLOAD_FOLDER`; the rewritten path layers a `'..' in rel.split('/')` check at the call site on top of `_check_safe_subpath` inside the storage layer (defence in depth — either guard alone is sufficient).
- **Env vars**: `UPLOADS_BACKEND` (selector), `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` (set for R2/MinIO/Wasabi; leave unset for AWS), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_FORCE_PATH_STYLE` (`1` for MinIO and some on-prem proxies; `0` or unset for AWS / R2 / Wasabi), `UPLOADS_PUBLIC_BASE_URL` (optional CDN domain — when set, `url_for()` returns `https://cdn.example.com/<key>` instead of the proxied `/uploads/<file>` route, freeing the Flask process from serving bytes at all).
- **When to switch**: the local backend is correct for `python app.py` development, single-machine VPS deploys with persistent disk, and any single-worker container with a mounted volume. Switch to `s3` for any host with an ephemeral FS (Replit deploys, Heroku-style PaaS, Fly machines without volumes), any multi-worker `gunicorn -w N` setup behind a load balancer, or any time you want a CDN in front of media (`UPLOADS_PUBLIC_BASE_URL` to a CloudFront / R2 public hostname).
- **Verification**: storage roundtrip smoke test added at the end of `tests/test_smoke.py` (`test_storage_write_read_delete_roundtrip` + `test_storage_singleton_returns_known_backend`), so the suite now defends 39 paths (37 pre-existing + 2 storage). All 39 still pass against the default `UPLOADS_BACKEND=local`. Boot log after restart shows the existing 595 files still serve (`GET /uploads/9e8b16b913a264a4.jpeg HTTP/1.1 304`, `GET /uploads/voice/2f0587e3749ef7…mp3 HTTP/1.1 206`) — proof the legacy disk path is unbroken.

## API Cache Headers (Optimization #3 — April 2026)

Third item from the perf list. Public read-only `/api/*` endpoints serve content the operator edits at most once a week (site settings, gallery, blog, services, theme, etc.) but were re-fetched on every page load — and would re-ask the origin from any CDN sitting in front of the app. Optimization #3 adds an `after_request` hook in `app.py` that pins exactly `Cache-Control: public, max-age=60, stale-while-revalidate=300` on a tight, explicit allowlist of 21 public read endpoints (the bundle from Optimization #1 + its 17 sources + `/api/theme` + `/api/chatbot-settings` + `/api/voice/settings`).

- **Allowlist not denylist**: kept in a `_CACHEABLE_API_PATHS` frozenset right above the hook. Adding a new public read endpoint requires an explicit two-line edit (frozenset + matching `EXPECTED_CACHEABLE_PATHS` in `tests/test_cache_headers.py`); this trades "miss a perf win" against "accidentally cache `/api/admin-something` for the world" — the second blast radius is much larger, so the allowlist wins.
- **Six-guard safety**: the hook bails BEFORE setting Cache-Control on (1) non-GET requests, (2) non-200 responses, (3) paths not in the allowlist, (4) responses that already chose their own `Cache-Control` (preserves the `no-cache` on the SSE chat/voice streams at lines 14822 / 16148 and the `no-store` on TTS prepare at 22672 — never overwritten), (5) responses carrying a `Set-Cookie` header (anti-session-bleed: a CDN sharing one cached entry could replay another user's session cookie), (6) requests carrying a Flask session cookie at all (admin-might-be-logged-in heuristic, so admins editing content always see fresh writes).
- **Why we check `request.cookies` instead of `session`**: reading `session.get(...)` marks the session as accessed and Flask auto-injects `Vary: Cookie`, which fragments any downstream CDN cache across every cookie value clients send (`_ga`, `lang`, A/B bucket, etc.) — largely defeating the `public` cache. We use `SESSION_COOKIE_NAME in request.cookies` so the hook never touches the session object; verified with the behavioral `test_anonymous_response_has_no_vary_cookie` and `test_non_session_cookies_still_get_public_cache` regression tests, and an `in`-not-`.get()` check so a present-but-empty session cookie also triggers the skip.
- **TTL choice**: 60s of fresh-cache (refresh within a minute hits the browser cache instantly), 300s of `stale-while-revalidate` (between 60s and 360s the browser shows the stale copy AND silently revalidates in the background, so users never wait even past expiry). `public` lets a CDN share one cached entry across every anonymous visitor — the big win once `UPLOADS_PUBLIC_BASE_URL` and a CDN go in front of the origin. For weekly-edit content this is conservative; tightening to `max-age=300, swr=900` is a one-line bump if the operator wants more aggressive caching.
- **Verification**: `tests/test_cache_headers.py` defends 30 paths — a parametrized assertion for each of the 21 cacheable endpoints (drift-guarded against `_CACHEABLE_API_PATHS` so they can't go out of sync), plus 9 contract tests covering the negative cases (admin path, non-allowlisted public path, POST to a cacheable path), the existing-Cache-Control / Set-Cookie / session-cookie skips, the no-`Vary: Cookie` regression, and the CDN-sharing guarantee with realistic third-party cookies. Wire-confirmed: `curl /api/page-bundle` returns `Cache-Control: public, max-age=60, stale-while-revalidate=300` AND `Vary: Accept-Encoding` (no Cookie); `curl -b session=fake /api/page-bundle` returns no Cache-Control header (admin escape hatch works).

## Image Optimization (Optimization #4 — April 2026)

Fourth item from the perf list. The `/uploads/` directory was serving original-size JPEGs / PNGs on every page — a 4 MB phone-camera hero photo getting downloaded by a 360 px wide phone wastes 95% of those bytes. Optimization #4 adds a new `image_optimize.py` module that produces three responsive WebP variants (`<stem>-400.webp`, `<stem>-800.webp`, `<stem>-1600.webp`) for every JPEG / PNG, plus a tiny frontend helper (`imgSrcset` / `imgAttrs` in `public/script.js` near `escapeHtml`) that emits the `srcset` + `sizes` attributes browsers need to pick the right one.

- **Why WebP, not AVIF**: Pillow 12.x has WebP built in, no extra package. AVIF needs `pillow-avif-plugin` AND encodes 3-10× slower than WebP for ~10% more savings — a worse trade for the on-demand path where a viewer is blocking on the response. AVIF can be added later as a `<picture>`-with-`<source>` upgrade with WebP as the broad fallback.
- **Why these three widths**: 400 (phones at 1× DPR + tablet thumbnails), 800 (phones at 2× DPR + tablet 1× + half-width desktop cards), 1600 (desktop hero + 2× of 800 for retina). Anything > 1600 isn't generated — uploaded photos rarely exceed that and shipping 4K backgrounds to a 4K monitor is a problem we don't have today.
- **Two-track generation**: (1) **Pre-warm on upload** — `admin_upload_image` (`app.py:19826`) and the image branch of `admin_upload_media` (`app.py:19898`) both call `image_optimize.generate_webp_variants(unique_name)` after the original is written via `storage.get_storage().write_fileobj(...)`. The call is wrapped in `try/except` + `app.logger.exception` so a Pillow decode failure on an oddball file never fails an upload. (2) **On-demand for legacy 595 files** — `serve_upload` (`app.py:19801`) checks `image_optimize.is_variant_filename(filename)` and, if it matches `<stem>-<width>.webp`, calls `ensure_variant_on_demand` BEFORE `storage.serve()`. Idempotent (no-op if the variant already exists), single-variant (only generates the requested width, not all three), zero schema changes — the first viewer who requests a legacy variant pays the resize cost (~150-500 ms once), every subsequent request hits the cached variant directly. This means the frontend can unconditionally point at variant URLs without a separate one-shot backfill script.
- **Pre-warm vs on-demand asymmetry on small sources** (`_encode_webp(cap_to_source=...)` flag): the pre-warm path REFUSES to upscale — a 300×200 thumbnail goes through `generate_webp_variants` and produces zero variants, because storing three near-identical WebPs of a tiny image is just wasted disk. The on-demand path takes the OPPOSITE choice: it CLAMPS the requested width down to source width, so a viewer hitting `/uploads/abc-800.webp` with a 300px source still gets a valid 300px WebP back (HTTP 200), not a 404. Why the asymmetry: the frontend `imgAttrs(url, sizes)` helper emits all three variant URLs without knowing source dimensions, so a 404 on the small-source case would cost every page load with a tiny image one wasted round-trip before the browser falls back to `src=` (and that 404 isn't reliably cached by every CDN). Encoding at source-width on demand costs ~150 bytes of disk (a 300px WebP is tiny) and saves the round-trip. Live-confirmed: the 300×200 legacy file `1d97bf67445092d8.jpg` (1616 B) gets an on-demand 800w variant that's a valid 300×200 WebP at 196 B; the 1440×811 file `2f1e6ce5e0bea057.jpg` (136 KB JPEG) gets a real 800×451 downscale at 32 KB (76% smaller, the actual perf win).
- **Why `<img src/srcset/sizes>` and not `<picture>`**: the user explicitly asked for `<img srcset>` and that's all this optimization needs. WebP has 95%+ browser support (Safari 14+ since 2020), so we just rewrite to WebP universally — no per-format `<source>` fallback dance. If a browser doesn't pick any srcset candidate (or one fails to fetch), it transparently falls back to the original JPEG/PNG via the `src=` attribute.
- **Frontend wiring (6 high-traffic sites)**: `imgAttrs(url, sizes)` in `public/script.js` near `escapeHtml` is now used by — (1) testimonial avatar (line ~411, `sizes="80px"`), (2) team member photo (line ~444, `sizes="120px"`), (3) store product card (line ~813, `sizes="(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw"`), (4) custom store-card render (~line 2126, same sizes), (5) admin custom-service-card render (line ~2089, `sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"`), (6) experience services-card render (line ~8335, same). The `sizes` attribute is REQUIRED for srcset to be useful — without it the browser assumes 100vw and downloads the LARGEST variant, which would be worse than the original for an 80 px avatar. `imgAttrs` enforces this: when `sizes` is omitted, it emits plain `src=` only.
- **CSS `background-image` sites NOT covered (deferred follow-up)**: gallery cards (`script.js:322`), blog covers (`script.js:532`), custom card image (`script.js:1796`), custom gallery item (`script.js:1825`), gallery slide bg (`script.js:2182`) — these use `style="background-image: url(...)"` for which `srcset` doesn't apply. The proper fix is `image-set()` in CSS (universal browser support since 2023), but that's a separate styling refactor. Listed as a follow-up.
- **Frontend / backend rule parity**: `imgSrcset` in JS and `srcset_for` in Python make IDENTICAL decisions — same eligible extensions (jpg, jpeg, png), same widths emitted (400/800/1600), same top-level-only check (subpath `/uploads/voice/...` returns ''). If you change one, change the other. The module docstring on each side says so explicitly.
- **Verification**: `tests/test_image_optimize.py` adds 49 cases across three layers — (1) **pure helpers**: 15 parametrized cases for `is_variant_filename` (valid widths, invalid widths, non-webp, subpath, no extension) + 16 for `srcset_for` (eligible URLs emit all three widths in stable order, ineligible URLs yield '' for gif/webp/svg/subpath/external/empty); (2) **generation round-trips**: JPEG yields three smaller variants, PNG-with-alpha keeps RGBA through the WebP encode, source < smallest breakpoint yields zero variants, source between breakpoints yields a partial set, GIF/WebP/corrupt-bytes/missing-source/non-image-extension all return `[]` without raising; (3) **on-demand correctness**: missing-variant-with-source generates and persists, idempotent on the second call, returns False for no-source / non-variant-filename / subpath / invalid width, AND a defensive case proving a user-uploaded `vacation.webp` is NEVER overwritten by an on-demand call; (4) **Flask integration via test_client**: `GET /uploads/<stem>-800.webp` for an unwarmed legacy file returns 200 + valid WebP bytes + width=800 AND persists the variant for next time, missing-source yields a clean 404 (no 500). Full suite now 143/143 (94 prior + 49 new), all green on the first run.

## How to Edit Content

1. Go to `/admin` in your browser (password: set via ADMIN_PASSWORD env var, default "admin")
2. Use the tabs to switch between Site Settings, Gallery Cards, Experiences, Pricing, Chatbot, Chat History, Forms, and Theme
3. Click "Edit" on any item to modify it, or "+ Add" to create a new one
4. Drag rows to reorder gallery cards, experiences, pricing, and form fields
5. Upload images directly from the admin panel
6. Create custom forms with any combination of field types
7. View form submissions with full marketing analytics
8. Changes are saved to the database immediately
9. Reload the public site to see your changes

## How to Customize the Template

### Change the visual style
Use the Theme Editor in admin to change colors, fonts, and glass effects — no code editing needed.
For advanced customization, edit `public/styles.css` — every section is commented with what it controls.
Key variables are in the `:root` block at the top (fonts, colors, spacing, animation timing).

### Change the page structure
Edit `public/index.html` — the HTML structure is fully commented.
Add new sections inside the `.landing-container` div with classes `snap-section landing-section`.

### Add a new content type
1. Create a new database table in the `init_db()` function in `app.py`
2. Add public API route (GET) and admin API routes (GET/POST/PUT/DELETE) in `app.py`
3. Add rendering code in `public/script.js`
4. Add the admin form and table in `templates/admin/dashboard.html`

## External Dependencies

### Required Environment Variables
- `DATABASE_URL` — PostgreSQL connection string (provisioned by Replit)
- `ADMIN_PASSWORD` — Admin dashboard login password (default: "admin")
- `FLASK_SECRET_KEY` — Session encryption key (auto-generated if not set; also signs unsubscribe tokens)
- `AI_INTEGRATIONS_OPENAI_API_KEY` — OpenAI API key (set by Replit AI Integrations)
- `AI_INTEGRATIONS_OPENAI_BASE_URL` — OpenAI base URL (set by Replit AI Integrations)
- `SENTRY_DSN` — (Optional) Sentry error tracking DSN
- `SENTRY_ENV` — (Optional) Sentry environment tag (default: "production")
- `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` — (Optional fallback) Used if the Replit Stripe connection is not configured
- `STRIPE_WEBHOOK_SECRET` — (Optional) Validates incoming Stripe webhooks; if unset, signatures are not enforced (dev only)
- `RESEND_API_KEY` / `RESEND_FROM_EMAIL` — (Optional fallback) Used by the Messaging system if the Replit Resend connection is not configured
- `RESEND_WEBHOOK_SECRET` — (Optional) Svix secret used to verify `/webhooks/resend`; if unset, the endpoint is fail-open (dev only)
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` — Required to send SMS via the Messaging system; Twilio is **env-only** (no Replit connector)
- `ADMIN_EMAIL` / `ADMIN_PHONE` — Default destinations for "test send" in the Messaging admin

### Python Packages
- `flask` — Web framework
- `psycopg2-binary` — PostgreSQL driver
- `openai` — OpenAI API client for the AI chatbot
- `stripe` — Stripe SDK for payments, customers, and refunds
- `gunicorn` — Production WSGI server
- `sentry-sdk[flask]` — Error tracking (optional, enabled via SENTRY_DSN)

### Storefront & Payments
The template includes a full storefront ("Store" page section) with cart, Stripe Elements
checkout, and Stripe-emailed receipts. Stripe is sourced via the Replit Stripe connection
(preferred — keys auto-rotated by Replit) with a raw `STRIPE_SECRET_KEY` env var fallback.
Webhook endpoint `/api/stripe/webhook` handles `payment_intent.succeeded` (marks order paid,
decrements stock), `payment_intent.payment_failed`, and `charge.refunded`. Admin tabs
"Products" and "Orders" provide CRUD, inventory adjustments, and one-click refunds.
Database tables: `products`, `customers`, `orders`, `order_items`.

### CDN Dependencies
- Google Fonts (Playfair Display, DM Sans, plus dynamic fonts via Theme Editor)
- Lucide Icons
- SortableJS (drag-and-drop reordering in admin)
- DOMPurify (HTML sanitization for AI-generated content)

## Project File Structure

```
app.py                          — Flask backend (main entry point, all routes + API)
public/
  index.html                    — Public site HTML structure (SEO meta tags injected server-side)
  styles.css                    — All visual styles
  script.js                     — All interactivity, AI chat, visitor tracking
uploads/                        — Uploaded image files (created at runtime)
templates/
  admin/
    dashboard.html              — Admin panel (content management, SEO, blog, analytics)
    login.html                  — Admin login page
  blog_post.html                — Individual blog post page template
chat-ui-kit/                    — Standalone sellable chat UI template package
  chat-ui.css                   — Chat widget styles (frosted glass, responsive)
  chat-ui.html                  — HTML partial (chat bar, panels, canvas, split-screen)
  chat-ui.js                    — Self-contained JS module (ChatUI namespace)
  README.md                     — Full package overview and setup instructions
  PROMPT_GUIDE.md               — AI system prompt writing guide with command reference
  INTEGRATION_GUIDE.md          — How to wire the chat to control any website
  backend/
    schema.sql                  — PostgreSQL schema for all chat tables (7 tables)
    server.py                   — Reference Flask backend with all API routes
    admin.html                  — Standalone admin dashboard (frosted glass dark theme)
GUIDE.md                       — Developer guide for customizing the template
pyproject.toml                  — Python package dependencies (source of truth)
uv.lock                         — Python dependency lock file
requirements.in                 — Mirror of pyproject deps for Docker / buildpacks
Dockerfile                      — Production container image (libreoffice + gunicorn)
docker-compose.yml              — One-command local spin-up (app + Postgres + volume)
.env.example                    — Full env-var inventory with required/optional labels
README.md                       — Human-facing quickstart for new operators
DEPLOY.md                       — Per-platform deployment recipes (Render/Fly/Railway/VPS)
replit.md                       — This documentation file (agent-facing)
.replit                         — Replit run/deploy configuration
```
