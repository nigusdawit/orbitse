# Database-Driven Website Template

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
- **AI Live Site View** — every chat message injects the current site state into the AI's context: brand identity, theme tokens, gallery cards, experiences, pricing, dynamic forms, testimonials, team, FAQs, blog posts, last 25 AI-generated pages, business contact, the full landing page layout (every section in display order with enabled/DISABLED status), and items inside admin-created custom sections (title, subtitle, content, icon, image, link)
- **Image Upload System** — upload images directly from admin, stored in `/uploads/`
- **Drag-and-Drop Reordering** — reorder gallery cards, experiences, pricing, testimonials, team, and FAQ by dragging rows
- **Toggleable Sections** — enable/disable Testimonials, Team, FAQ, and Footer from admin
- **Business Info & Social Links** — manage contact details, hours, and social media profiles from admin; dedicated landing page section with contact info cards and embedded Contact Us form
- **Contact Us Form** — database-driven contact form (slug: `contact-us`) with name, email, subject, message fields; submissions appear in admin Forms tab; also available as AI chatbot form collection
- **Testimonials/Reviews** — client quotes with star ratings, reviewer names/roles
- **Team/About** — team member cards with photo, name, title, bio
- **FAQ** — collapsible question/answer pairs
- **Page Layout Manager** — drag-to-reorder all site sections from admin, toggle sections on/off
- **Custom Section Builder** — create new sections from admin using 11 templates: 6 layout templates where you author the items (cards grid, text content, image gallery, CTA banner, stats counter, icon features) plus 5 data-showcase templates that auto-pull from your existing libraries (events, rsvp_form, video_gallery, podcast, products). Data-showcase templates hide the per-section items UI; the rsvp_form template prompts for an event slug on Edit and stores it in section.subtitle.
- **Event Ticketing & Donations** — events support three price modes: `free` (RSVP only), `paid` (Stripe Checkout for fixed price × guests), and `donation` (visitor-entered amount, optional minimum, "pay what you wish" flow). Free RSVPs are saved immediately; paid/donation RSVPs are saved with `payment_status='pending'` then redirected to Stripe Checkout — the row flips to `paid` via the `checkout.session.completed` webhook (idempotent, FOR UPDATE) and to `expired` via `checkout.session.expired`. Capacity is reserved at the moment the RSVP row is created so seats can't be double-sold while the visitor is in Checkout.
- **Blog System** — database-driven blog with gallery-style preview cards on landing page, full post pages with SEO meta tags, admin management with draft/publish workflow
- **SEO Management** — admin tab for meta title, description, keywords, Open Graph, Twitter Cards; AI-powered SEO suggestion generator; auto-generated sitemap.xml and robots.txt; JSON-LD structured data
- **Visitor Analytics** — page view tracking with UTM params, device/browser/OS breakdown, referral sources, session duration; admin dashboard with charts and stats
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

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.
The entire template is industry-agnostic — naming, comments, and instructions avoid hotel/villa-specific language.

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
- KPI cards show visitors today / this week, page views today, new leads, chat sessions, and revenue (auto-hidden when zero)
- 14-day visitor trend chart powered by Chart.js
- Recent submissions list with form name, preview, and relative time
- Manual Refresh button + "Updated HH:MM:SS" indicator
- Backend endpoint: `GET /admin/api/overview/stats` aggregates from `page_views`, `form_submissions`, `chat_conversations`, `orders`

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
- **Actions** (run in order): `send_email`, `send_sms` (use messaging.py's providers and templates), `ai_draft` (OpenAI chat completion, model defaults to `gpt-4o-mini`), `http_request` (GET/POST/PUT/PATCH/DELETE with optional headers and JSON body, 15s timeout), `save_to_table` (insert into any non-blocklisted table via the existing internal-DB helpers), `delay` (1–300 seconds)
- **Merge tags**: every config field is rendered with `{{trigger.fields.email}}`, `{{step1.text}}`, `{{step_my_step_name.status}}` style placeholders before the action runs; renderer recurses into nested dicts/lists
- **Engine**: `automations.py` registers a tick callback with `messaging.py`'s 30s scheduler — no extra threads. Per-run worker thread, `120 s` overall timeout, max 5 concurrent runs (semaphore), 60 runs/hour/automation rate limit
- **Run log**: every dispatch creates an `automation_runs` row with `status` (queued/running/succeeded/failed/timeout), `step_results` JSONB (one entry per step with config-rendered, output, ok flag, elapsed_ms), `is_dry_run` flag, and `triggered_by` source. Visible in the editor with re-run button
- **Test runs**: editor has a "Run now" panel that fires the automation with admin-supplied JSON sample data and polls the run row until it finishes; "dry-run" checkbox flags the row in the log (actions still execute for real)
- **Webhook security**: tokens are 32-char URL-safe random; a partial unique index covers only non-null tokens; `/automations/hook/<token>` only fires when `enabled=TRUE` and `trigger_type='webhook'`
- **Versioning**: every meaningful save (create / update / restore) appends a snapshot to `automation_versions` (`name`, `description`, `trigger_type`, `trigger_config`, `action_steps`); identical-content saves are de-duped so the history stays useful. The editor has a "Version history" button that opens a modal listing every saved version with a one-click "Restore" — the restored copy keeps the live on/off setting and is itself written as a new version, so no history is ever lost. Schema-drift safety: a restored snapshot is re-validated against the current trigger and action catalogues, so versions referencing a removed action kind fail cleanly with 422.
- **Import / export (cross-site sharing)**: per-row "Export" button downloads a self-contained JSON file (`schema: "automation/v1"`); list-view "Import" button uploads any such file (256 KB cap) and creates a new automation. Imports are forced to `enabled=FALSE` so the admin can review credentials, table refs, and webhook URLs before turning it on; webhook tokens are always re-minted on import; name collisions get an `(imported N)` suffix
- **Database tables**: `automations`, `automation_runs`, `automation_versions`
- **Module**: engine, registry, dispatch, rate-limit, and scheduler tick live in `automations.py`; admin routes (CRUD + versions + import/export) and the public webhook live in `app.py`

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
pyproject.toml                  — Python package dependencies
uv.lock                        — Python dependency lock file
replit.md                       — This documentation file
.replit                        — Replit run/deploy configuration
```
