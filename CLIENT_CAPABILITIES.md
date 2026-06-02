# What Your Site Can (and Can't) Do

A plain-language reference for clients and operators. Everything here describes what's actually shipped in the platform today — no roadmap items, no marketing fluff. For features that are *planned* but not yet built, see `FUTURE_FEATURES.md`.

> **How to read this doc**
> - ✅ **Available now** — works out of the box.
> - 🔑 **Available, but needs an API key** — feature is built; works once you paste the credential into the admin secrets panel.
> - 💎 **Plan-gated** — built in, but only enabled on certain pricing tiers.
> - ⛔ **Not yet available** — link to `FUTURE_FEATURES.md` if it's on the roadmap.

---

## 1. Your AI Assistant (the chatbot on your site)

### What it can do today ✅
- Hold a conversation with your visitors in natural language, on any page of the site.
- Answer questions about everything you've put into your admin: services, pricing, events, blog posts, team, FAQs, products, business hours, contact details.
- Show visitors a specific gallery slide, scroll to a section, or open a custom-generated page on demand ("show me your wedding packages" → it builds a styled page live).
- Speak its replies out loud (text-to-speech) and listen to spoken visitor questions (speech-to-text).
- Greet visitors with a personalised audio intro based on where they came from (e.g. a visitor coming from a Facebook ad hears a different welcome than one coming from Google).
- Collect form submissions inside the chat (e.g. "what's your email so I can send the menu?").
- Render formatted replies (headings, bullets, tables, links) — not just plain text.
- Remember the full conversation for that visitor's session.
- Be turned on or off site-wide from the admin.
- Use a system prompt you fully control — change its tone, personality, or knowledge focus without touching code.
- Reply faster: the assistant now reuses a cached copy of its fixed instructions instead of re-reading them on every message. This is automatic for every site — replies come back quicker (and cost a little less) with no change to what the assistant says or does.

### What you control ✅
- Which voice it uses (six OpenAI voices for fast/cheap, or any ElevenLabs voice for ultra-realistic).
- Which TTS / STT provider (OpenAI is cheaper, ElevenLabs is more lifelike).
- Whether it speaks at all, or just types.
- Per-visitor daily voice character cap (anti-abuse).
- The exact wording of every greeting.
- **Optional "specialist router"** (OFF by default) — when you turn it on, the assistant first figures out what each visitor is asking about (booking, pricing, a general question, or leaving their details) and loads only the instructions and tools that fit, for an even faster, more focused reply. It's fully under your control (a master on/off switch, the classifier model, a confidence setting, and five editable prompts). If it's ever unsure, it quietly falls back to the full assistant — so chat never breaks. Until you switch it on, nothing changes.

### Cost transparency ✅
- Every chat message, every voice second, every SMS segment is logged with its cost.
- A **Cost** tab in admin shows month-to-date spend, with a chart and breakdown by feature (visitor chat / admin chat / voice / SMS / page generation).
- You can set a monthly **cost cap**: alert-only, throttle (degraded service when over budget), or hard-block (returns "cap reached" instead of paying the AI provider).
- Optional **weekly digest email** summarising spend, top conversations, and top forms.

### What it can't do ⛔
- It cannot take phone calls. (Voice is browser-only today.)
- It cannot proactively message past visitors out of the blue. (Triggered automations can — see Section 3.)
- It cannot pretend to be a human or override the disclosure that it's AI.

---

## 2. Extending the AI with Your Own Tools (advanced)

This is one of the most powerful parts of the platform and most clients don't realise they have it.

### MCP Connectors ✅
**MCP** (Model Context Protocol) lets you plug *any* external tool into the AI. The admin **MCP Servers** tab lets you connect:
- Your own internal APIs.
- Third-party services that publish an MCP server (a fast-growing list — examples: GitHub, Linear, Notion, Slack, Figma, custom databases).
- Your own scripts running anywhere reachable over HTTP.

Once connected, the AI can call those tools mid-conversation. Example: a real-estate client connects their MLS database via MCP; visitors can then ask "show me 3-bedrooms under $500k in Dallas" and the AI queries the MLS live.

### Custom Skills ✅
The admin **Skills** tab lets you define new AI capabilities without code:
- **Built-in skills** — toggle on/off the ones the platform ships with (lookup gallery, lookup services, web search, etc.).
- **Custom SQL skills** — write a SQL query against your own database and expose it to the AI as a named tool.
- **Custom HTTP skills** — point at any REST endpoint and the AI can call it with arguments you define.

### What this means in practice ✅
You can teach the AI almost anything specific to your business, without paying for custom development. If you can describe it as "call this URL with these parameters" or "run this SQL", the AI can do it.

### What it can't do ⛔
- Skills can't run arbitrary shell commands on the server (security boundary).
- Skills can't modify the platform's own code.
- Skills are visible to the AI on every chat — if you have many, the AI gets slower; we recommend keeping the active set under ~30.

---

## 3. Automations (if-this-then-that workflows)

The **Automations** tab lets you build workflows that run when something happens on your site, without touching code. This is the same engine used internally by the review collector, the weekly digest, and the scrape scheduler — so it's battle-tested.

### Triggers (the "if X" part) ✅
- A specific (or any) form is submitted.
- A new chat conversation starts.
- A schedule fires (every N minutes, or daily at a fixed time).
- An external service POSTs to your webhook URL (with built-in signature verification for Stripe and GitHub, plus a generic HMAC option).
- A "manual run" button (for testing).

### Actions (the "then Y" part) ✅
- Send an email (via Resend).
- Send an SMS (via Twilio — needs real Twilio credentials).
- Have the AI draft text (e.g. a personalised reply).
- Make any HTTP request (GET / POST / PUT / PATCH / DELETE).
- Save data to your database.
- Wait N seconds before the next step.
- Branch on a condition (e.g. "only continue if email contains @gmail").
- Call any skill, MCP tool, or custom SQL skill defined in Section 2.

### What this can't do today ⛔
- Cannot trigger from social media comments / DMs (planned — see `FUTURE_FEATURES.md` Tier 13).
- Cannot trigger from incoming phone calls (no telephony integration today).
- Cannot trigger from incoming emails (no inbox-watcher today).

---

## 4. Selling, Booking, and Taking Payments

### Service bookings ✅
The **Services** tab supports four pricing models per service:
- **Free RSVP** (no payment, just a reservation).
- **Deposit** (Stripe Checkout for the deposit; remainder owed offline).
- **Full payment** (Stripe Checkout for the full price).
- **Contract upload** (you upload a PDF/DOC template; the client downloads, signs offline, re-uploads via a tokenised link).

Plus optional **add-ons** (priced extras) the client multi-selects at booking time, and optional **calendar availability** (recurring weekly rules + per-date overrides) — slots automatically disappear from the public booking calendar as they fill.

### Event ticketing ✅
The **Events** tab supports three price modes:
- **Free** (RSVP only).
- **Paid** (fixed price × number of guests via Stripe).
- **Donation** ("pay what you wish", with optional minimum).

Capacity is reserved at the moment of RSVP so seats can't be double-sold while the visitor is in checkout.

### Products ✅
The **Products** tab supports a simple product catalogue with Stripe Checkout.

### What it can't do ⛔
- No subscription/recurring billing for end-customers (Stripe Checkout one-time only today).
- No multi-currency at checkout (Stripe charges in your configured currency).
- No invoice PDF generation for end-customers (Stripe sends its own receipt; no branded PDF on top).
- No physical-product shipping integration (no inventory management, no shipping label printing).

---

## 5. Content & Site Management

### Pages and sections ✅
- **Page Layout Manager** — drag to reorder every section on the landing page; toggle any section on/off.
- **Custom Section Builder** — drop in new sections from 11 templates (cards grid, text content, image gallery, CTA banner, stats counter, icon features, plus 5 data-pulling templates that auto-show your events / RSVP form / video gallery / podcast / products).
- **Sphere View** — fullscreen 3D experience with two modes (orbiting card carousel or rotating image sphere).
- **AI-generated pages** — the AI can build a fully animated page on demand from a visitor request, save it, and reuse it later.

### Blog ✅
- Rich text editor (bold, italic, headings, lists, links, images) — no HTML required.
- Draft / publish workflow.
- Reading-progress bar on post pages.
- Auto SEO (meta tags + Open Graph + JSON-LD).

### SEO ✅
- Per-page meta title, description, keywords, Open Graph image, Twitter card.
- AI-powered meta description generator.
- Auto-generated `sitemap.xml` and `robots.txt`.
- JSON-LD structured data for search engines.
- Per-section SEO overrides for pretty URLs (`/podcast`, `/events`, etc.).

### Theme & branding ✅
- Live theme editor for colours, fonts, glass effects, dark mode.
- Cursor mode, scroll progress bar, navigation style, chatbot placement — all switchable from the **Personality** controls.

### Forms ✅
- Drag-and-drop form builder.
- Multi-step forms with field-to-step assignment.
- Auto-save partial submissions (lead recovery).
- Full marketing analytics on every submission (UTM, referrer, device, screen size, language).

### Reviews ✅ / 🔑
- AI **Review Collector** — auto-emails / SMS-asks customers for a review N days after they paid.
- Each ask carries a unique tracking link (click + conversion attribution).
- The AI drafts the personalised ask using a template you control.
- Aggregates star ratings from **Google Places**, **Yelp**, **TripAdvisor** 🔑 (needs each respective API key).

---

## 6. Analytics & Insights

### Visitor analytics ✅
- Page views, sessions, session duration, bounce.
- UTM parameter tracking (source / medium / campaign / content / term).
- Device / browser / OS breakdown.
- Referral sources.

### Chat analytics ✅
- Every conversation logged with full transcript.
- Per-turn breakdown of which AI tools were used to answer (transparency into "how did the AI know that?").
- Message counts, device types, session length.

### Form analytics ✅
- Every submission with full marketing attribution.
- Partial / abandoned submission capture for lead recovery.

### Cost analytics ✅
- See Section 1 — the Cost dashboard tracks every paid AI / voice / SMS call.

---

## 7. The Web Scraper (a quietly powerful tool)

The admin **Web Scraper** tab can pull content from any public webpage and turn it into structured data the AI can use.

### What it does ✅
- **URL mode** — paste a URL, the scraper fetches it (with safety guards) and extracts content.
- **Objective mode** — describe what you want ("find the menu prices for X restaurant"), the AI uses web search to find and extract it.
- Output shapes: free-form notes, gallery card, pricing tier, blog post, contact details, custom JSON.
- Push results directly into your tables as drafts (gallery cards, pricing, blog).
- **Recurring schedules** — auto-scrape hourly / daily / weekly; email or SMS the admin on completion or only on change.
- Auto-pause schedules that fail repeatedly (with a one-click resume).
- Optional **headless browser fallback** for JavaScript-heavy sites (ScrapingBee or Browserless 🔑).

### What it can't do ⛔
- Cannot scrape content behind a login wall.
- Cannot bypass CAPTCHAs.
- Will not scrape sites that explicitly disallow it via `robots.txt` (we respect this).

---

## 8. Communications

### Email ✅
- **Resend** integration for transactional emails (confirmations, review asks, weekly digest, automation actions).
- All sends logged in `messaging_log` for audit + delivery tracking.
- Webhook-based status updates (delivered / opened / bounced).

### SMS 🔑
- **Twilio** integration — currently using placeholder credentials. SMS campaigns, STOP-keyword opt-out, and inbound-SMS webhook will work once real Twilio credentials are added.
- E.164 number validation, segment counting, cost tracking per send.

### What's missing ⛔
- No WhatsApp Business integration (would be a Twilio sub-feature).
- No live chat with human operators (AI only).
- No social DM as a communication channel (planned — see `FUTURE_FEATURES.md`).

---

## 9. Operator-Side Tools (for you, not your visitors)

### Admin dashboard ✅
- Password-protected at `/admin`.
- ~25 tabs covering everything above.
- Drag-and-drop reordering throughout.
- Image upload directly in admin (stored in `/uploads/` or S3).

### Snapshot / Clone ✅
- Export a complete snapshot of one configured install as a JSON template.
- Apply that template to a fresh install to clone the configuration.
- Three surfaces: admin UI tab, master-agent VELO command, command-line script.
- Sensitive values (MCP tokens, automation secrets) auto-redacted by default.

### Developer console ✅
- Admin-side developer console for inspecting state and running diagnostics.

### Performance tab ✅
- Surface for monitoring response times, slow queries, and asset variant cleanup.

---

## 10. Multi-Tenant / Agency Operations (for the agency, not the end-client)

### What's there ✅
- Each end-client gets their own isolated Replit deployment with their own Postgres database.
- A **VELO master agent** can register all client installs and broadcast configuration / feature-flag changes to them.
- Per-tenant feature flags + plan tiers (`solo` / `growth` / `enterprise`). The **Datahub**, **Research Hub**, and **Content Studio** tools can now be switched on or off per client from **Plans & Features** (they're ON by default), alongside the existing per-tenant toggles.
- Per-tenant cost caps (alert / throttle / hard-block).

### What's not there yet ⛔
- **Agency billing** — the platform does not automatically charge end-clients a subscription. You currently bill them manually outside the platform. (Roadmap: add Stripe subscriptions tied to plan tiers.)
- **Bulk update broadcast** — pushing a code fix to all client installs is currently a manual per-deployment redeploy. (Roadmap: master-driven `git pull && restart` broadcast.)
- **Multi-worker scaling** — some rate limiters are in-process memory; safe up to a single worker per install. Multi-worker production needs Redis/Postgres-backed limiters.

---

## 11. Quick "Can / Can't" Cheat Sheet

| Capability | Status |
|---|---|
| AI chat on the website | ✅ |
| AI voice (speak + listen) | ✅ |
| AI generates custom pages on demand | ✅ |
| AI uses your own tools (MCP, SQL, HTTP) | ✅ |
| Trigger automations from forms / chats / schedules / webhooks | ✅ |
| Take payments (one-off, deposits, donations) | ✅ |
| Bookings with calendar + add-ons + contracts | ✅ |
| Event ticketing | ✅ |
| Blog with rich text editor | ✅ |
| SEO with auto sitemap + JSON-LD | ✅ |
| Visitor + chat + form analytics | ✅ |
| Cost tracking + caps + weekly digest | ✅ |
| Theme + dark mode + personality controls | ✅ |
| Web scraping (single + recurring) | ✅ |
| Email sending (Resend) | ✅ |
| SMS sending (Twilio) | 🔑 needs credentials |
| Reviews aggregation (Google / Yelp / TripAdvisor) | 🔑 needs credentials |
| Snapshot / clone an install | ✅ |
| Subscription billing for end-customers | ⛔ |
| Subscription billing for agency-to-client | ⛔ |
| Push code updates to all clients at once | ⛔ |
| Post to Instagram / Facebook / TikTok | ⛔ planned (`FUTURE_FEATURES.md` Tier 11–14) |
| Run social media ads | ⛔ planned (Tier 15) |
| Auto-reply to social comments / DMs | ⛔ planned (Tier 13) |
| Live chat with human agents | ⛔ |
| Native mobile app | ⛔ |
| WhatsApp Business | ⛔ |
| Multi-language site (i18n) | ⛔ |
| Affiliate / referral program | ⛔ |

---

## 12. Things People Often Assume Work That Don't (yet)

Listing these explicitly so nobody is surprised:

1. **"Will the AI text my customers on its own?"** — Only if you wire an automation (Section 3) with a schedule trigger and an SMS action. The AI doesn't initiate outbound messages on its own.
2. **"Can I post to Instagram from the admin?"** — Not yet. You can store the link to your Instagram, but cannot post or DM. See `FUTURE_FEATURES.md`.
3. **"Will my clients get charged automatically every month?"** — End-customer purchases (one-off Stripe Checkout) yes. Recurring subscriptions, no — you bill agency-side manually today.
4. **"If I update the master codebase, do all my client sites update?"** — No, each is a separate deployment. Manual redeploy per client today.
5. **"Can the AI book a Zoom / Calendly meeting?"** — Only if you connect the relevant MCP server or add a custom HTTP skill that calls the Zoom/Calendly API. Not pre-built.
6. **"Does the chatbot remember a returning visitor across days?"** — Within a session yes; across sessions no (no cross-session memory layer today).
7. **"Can it transcribe a phone call?"** — No. Voice is browser-only.

---

*Last updated: alongside Tier 10 (snapshot/clone admin UI). When new tiers ship, update the relevant section above and move planned items out of `FUTURE_FEATURES.md` into the appropriate "✅ Available now" block.*
