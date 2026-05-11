# Future Features Roadmap

Living document for features that have been scoped and agreed-to but not yet built. Each section is sized so it can be lifted directly into a project task when the team is ready.

---

## Social Media Automation Suite (proposed Tiers 11–15)

**Why**: Today the platform stores social profile *links* (in `site_settings.social_links`) but cannot post, reply, DM, or run ads. For an agency selling this to small-business clients, social automation is one of the highest-perceived-value features still missing.

**What we already have that this builds on**:
- `automations.py` — multi-trigger / multi-action workflow engine (form_submitted, new_chat, schedule, webhook, manual triggers; send_email, send_sms, ai_draft, http_request, save_to_table, delay, condition, call_skill actions). New social triggers/actions slot directly into the existing registry.
- HMAC-SHA256 webhook signature verification (already used for Stripe + GitHub) — same pattern works for Meta's `X-Hub-Signature-256`.
- Scheduler tick infrastructure (used for review-asks, weekly digest, scrape schedules) — same pattern works for scheduled posts.
- `messaging_log` + cost ledger (`api_cost_events`, `voice_cost_events`, `sms_cost_events`) — extends naturally to a `social_cost_events` table or new surface enum.
- Per-tenant feature flags + `tenant_has_feature()` paywall — gates the whole suite to higher plan tiers.
- `/uploads` system + S3 backend — handles media attached to scheduled posts.

**What's new**: per-platform OAuth flows, token storage, posting clients, webhook receivers, comment/DM trigger types, scheduled-post calendar UI, ad-management dashboards.

---

### Tier 11 — Meta OAuth + Connection UI + Post-Now (foundation)

Estimated effort: 2–3 days of build (excluding Meta App Review wait time).

- **New table** `social_accounts (id, tenant_id, platform, account_id, account_name, access_token_encrypted, refresh_token_encrypted, expires_at, scopes_json, page_id, ig_business_id, connected_at, last_refreshed_at, status)`. One row per (tenant, platform, account). Tokens encrypted at rest using `FLASK_SECRET_KEY`-derived key.
- **OAuth flow**: `/admin/oauth/meta/start` → redirect to Meta consent → `/admin/oauth/meta/callback` writes the long-lived token + selected Page + linked IG Business id. Same flow handles both Facebook Pages and Instagram Business (Meta uses one OAuth, IG must be linked to a FB Page on the user's side).
- **Refresh job**: scheduler tick refreshes any token where `expires_at < NOW() + 7 days`.
- **Admin UI tab "Social"** with sub-tabs `Connections` / `Compose` / `Schedule` / `Automations` / `Insights`. Connections shows status badges per platform with one-click connect/disconnect.
- **Compose & post-now**: caption + media upload + per-platform preview + "Post now" button. IG flow is 2-step (create container → publish container); FB flow is single-call.
- **Cost surface**: new `social_post` row in the cost ledger (Meta API itself is free; row is for usage/auditing, not billing).
- **Plan gate**: new `social_basic` feature flag (defaults: solo=off, growth=on, enterprise=on).

### Tier 12 — Scheduled Posts + Calendar UI

Estimated effort: 2 days.

- **New table** `scheduled_posts (id, tenant_id, platforms[], caption, media_urls[], scheduled_for, status, posted_at, post_ids_json, error_text, retry_count, created_by)`. Status values: `pending` / `posting` / `posted` / `failed` / `cancelled`.
- **Scheduler tick** every minute: claims due rows with `INSERT … ON CONFLICT … RETURNING` to prevent double-post on multi-worker (same lock pattern as the weekly digest), calls the posting client, writes back `post_ids_json`.
- **Calendar view** in admin (Chart.js + a month grid component) — drag to reschedule, click to edit.
- **Bulk import**: CSV upload of "date, caption, media-url" for clients migrating from another scheduling tool.
- **Conflict guard**: warn the operator before scheduling two posts within 30 min on the same platform (Meta penalises burst posting).

### Tier 13 — Comment/DM Trigger Automations (the high-value tier)

Estimated effort: 3 days.

- **Webhook receiver** `/webhooks/meta` — verifies `X-Hub-Signature-256` against the app secret, routes events into the existing automation runner.
- **Two new triggers** registered in `automations.py:TRIGGER_TYPES`:
  - `instagram_comment` — config: account_id, post_filter (any / specific post id), keyword rules (regex / contains / exact)
  - `instagram_dm` — config: account_id, keyword rules
  - (Same for `facebook_comment`, `facebook_dm`.)
- **Two new actions** registered in `automations.py:ACTION_TYPES`:
  - `social_reply` — replies to the triggering comment thread
  - `social_dm` — sends a DM to the user (IG opens a 24-hour messaging window when a user comments first; we use that window to deliver the lead-magnet DM)
- **Templating**: actions support the existing variable substitution (`{{user.name}}`, `{{comment.text}}`, etc.) so admins can compose personalised replies without code.
- **Audit log**: every trigger fire + action result gets a row in `automation_runs` (existing table) so the admin sees "Comment 'send me the menu' on post X → DM'd menu PDF, succeeded".
- **TikTok caveat**: TikTok does NOT expose comment/DM webhooks. We will document this limitation in the trigger registry UI and offer "poll comments every N minutes" as a degraded fallback for TikTok in a later sub-task.

### Tier 14 — TikTok Posting (no DM/comment triggers)

Estimated effort: 2 days.

- **TikTok Login Kit OAuth** — separate flow, separate app review.
- **Content Posting API client** — chunked video upload (up to 4 GB), then publish. Captions, hashtags, privacy level (public / friends / private), allow comments/duet/stitch flags.
- **Hooks into Tier 12 scheduler** — `scheduled_posts.platforms` already supports `'tiktok'`, just needs the client wired in.
- **Honest UI labelling**: TikTok tab clearly states "posting + ads only — comment & DM automation are not available via TikTok's official APIs". Avoids client expectation mismatch.

### Tier 15 — Ads Management (Meta + TikTok)

Estimated effort: 1–2 weeks. Treat as its own project, not a sub-tier.

- **Separate APIs entirely** (Meta Marketing API, TikTok Marketing API) with separate OAuth scopes (`ads_management`, `ads_read`).
- **New tables**: `ad_campaigns`, `ad_sets`, `ad_creatives`, `ad_metrics_daily` (one row per ad per day per metric: impressions, reach, clicks, ctr, spend, conversions).
- **Daily metrics-pull job** — scheduler tick at ~03:00 UTC pulls yesterday's metrics for every active campaign across every connected ad account.
- **Dashboard**: campaign list with status badges, spend gauge, Chart.js line/bar of impressions+spend over time, drill-down to ad-set then ad-creative.
- **Create/pause/budget endpoints** — admin can launch a campaign from a saved creative + audience template without leaving the platform.
- **Ad-spend → cost ledger**: `ad_spend_synced` rows in the cost ledger so the agency can show clients "you spent $X on ads + $Y on AI usage this month" in one view.
- **Plan gate**: `social_ads` feature flag, enterprise tier only by default (ads imply higher revenue clients).

---

### Cross-cutting requirements (apply to all 5 tiers)

- **Token encryption**: never store OAuth tokens in plaintext. Reuse the same Fernet/AES helper that `mcp_servers.auth_credential` uses (Tier 6 already redacts these in snapshots — extend to `social_accounts`).
- **Snapshot integration**: `social_accounts` should be added to `scripts/snapshot.py` admin table list with auto-redaction of tokens (matches existing `mcp_servers` pattern). Receiving install reconnects each platform with its own OAuth.
- **Plan registry entries**: `social_basic` (Tier 11–14), `social_ads` (Tier 15) added to `_FEATURE_REGISTRY`.
- **Per-tenant rate limits**: Meta enforces ~200 calls/hr/user. Pre-throttle in our HTTP client to avoid surprises.
- **Cost-cap integration**: ad-spend rows feed `enforce_cost_cap()` so a strict-block tenant can't accidentally overspend on ads if the cap is set.

---

### Non-code blockers (start these in parallel with Tier 11 build)

These often take longer than the actual code:

1. **Meta App Review** — submit immediately; 1–4 weeks. Will require a screen recording demonstrating each requested permission (`instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`, `pages_read_engagement`, `pages_manage_posts`, `pages_messaging`, plus `ads_management` for Tier 15). 
2. **Privacy policy + Terms of Service URLs** — Meta requires public, hosted URLs at submission time.
3. **Business verification** — Meta requires this for the advanced permissions above.
4. **TikTok developer account + Content Posting API approval** — separate from Meta, separate timeline (~2 weeks typical).
5. **Per-client onboarding caveat** — each end-client must be admin on their own FB Page / IG Business account / TikTok Business account before the OAuth flow will succeed for them. Document this in the `Connections` UI with a "before you connect" checklist.

---

### Suggested build order

1. **Tier 11 first** (foundation — nothing else works without it).
2. **Tier 13 next** (highest perceived value — comment-to-DM is the killer demo).
3. **Tier 12 in parallel with Tier 13** if a second engineer is available.
4. **Tier 14** when at least one client asks for TikTok specifically.
5. **Tier 15 last** and only when at least one paying client has committed to ad budget.

### Out of scope for this roadmap

- LinkedIn, X/Twitter, YouTube, Pinterest, Threads — same patterns would apply, but each is its own OAuth + client + review cycle. Add as separate roadmap entries when a client asks.
- Comment/DM moderation AI (auto-hide spam, sentiment-flag negative comments) — natural Tier 16 once Tier 13 is live.
- Cross-posting (compose once, publish to N platforms with per-platform tweaks) — easy Tier 12 follow-up once Tier 11 + 14 are both shipped.
