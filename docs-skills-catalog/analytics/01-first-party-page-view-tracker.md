# First-Party Page-View Tracker

**Category:** Analytics
**Related:** `analytics/02-device-browser-os-breakdown.md`, `forms/04-utm-device-metadata-pipeline.md`, `admin-tooling/03-chartjs-admin-dashboards.md`

## When to use
You want first-party visitor analytics (page views, UTM attribution, session
duration, referrer source) without loading a third-party script (GA, Plausible,
PostHog). One Postgres table + one POST endpoint + a small browser beacon is
enough to power an admin dashboard with daily traffic, top pages, top
referrers, and device/browser/OS breakdowns.

## Architecture
- A single wide table (`page_views`) stores one row per page view.
- The browser POSTs to `/admin/api/analytics` on every page load (despite the
  `/admin/` prefix the endpoint is intentionally unauthenticated for ingest).
- The server fills in IP and parses the User-Agent (see skill #2) so the
  client only has to send what it knows (URL, referrer, UTM params, screen
  resolution, language, session_id, visitor_id).
- `session_id` is a per-tab/session UUID stored in `sessionStorage`;
  `visitor_id` is a long-lived UUID stored in `localStorage`. Together they let
  the dashboard count "sessions" vs "unique visitors" without cookies.
- A second beacon on `beforeunload` / `visibilitychange=hidden` PATCHes
  `duration_seconds` for the last row so bounce/dwell metrics work.

## Data model
Table `page_views` (`app.py:1678`, created in `init_db`):
- `id` SERIAL PK
- `session_id` TEXT — per-tab UUID
- `visitor_id` TEXT — long-lived UUID
- `page_url` TEXT
- `referrer_url` TEXT
- `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content` TEXT
- `ip_address` INET — set server-side from `request.remote_addr`
- `browser`, `os`, `device_type` TEXT — set server-side by `_parse_ua`
- `screen_resolution` TEXT (e.g. `1920x1080`)
- `language` TEXT (e.g. `en-US`)
- `country` TEXT — optional GeoIP enrichment
- `duration_seconds` INTEGER — backfilled on unload
- `created_at` TIMESTAMPTZ DEFAULT now()

Recommended indexes: `(created_at DESC)` for time-range queries,
`(session_id)` for dwell-time updates.

## API surface
- `POST /admin/api/analytics` — ingest (`app.py:27316`). Body:
  `{session_id, visitor_id, page_url, referrer_url, utm_*,
  screen_resolution, language}`. Returns `{row_id}` so the client can PATCH
  duration later.
- `GET /admin/api/analytics` — aggregate summary (`app.py:27388`).
- `GET /admin/api/analytics/chart` — daily time-series (`app.py:27507`).

## Key files
- `app.py:1678` — `page_views` schema
- `app.py:27316` — ingest endpoint
- `app.py:27388` — summary endpoint
- `app.py:27507` — time-series endpoint
- `public/script.js` — beacon (fires from `loadAllData` / unload listener)

## External deps
None. Pure Postgres + Flask + browser `fetch`. No third-party SDK.

## Pitfalls
- Don't gate ingest behind `@admin_required` — the public site must POST it.
  Validate inputs strictly instead (max URL length, UTM length, no PII).
- Use `sendBeacon` (or `fetch(..., {keepalive: true})`) for the unload PATCH;
  a normal `fetch` is cancelled when the page unloads.
- Strip query strings or hash from `page_url` before storing if those values
  carry secrets (e.g. password reset tokens).
- Rate-limit per-IP — a hostile client can flood this endpoint cheaply.
- Honor Do-Not-Track or a cookie-consent flag if your jurisdiction requires it.

## Adaptation notes
- For a multi-tenant SaaS, add `tenant_id` and an index on
  `(tenant_id, created_at DESC)`.
- Swap `INET` for `TEXT` on databases without an INET type.
- If you don't need GeoIP, drop the `country` column — adding it later is
  cheap with a backfill job that joins MaxMind on `ip_address`.
- Add `path` (URL pathname only) as a generated column to make "top pages"
  queries an index hit.

## Adoption checklist
1. Create `page_views` table.
2. Add the ingest route, server-fill IP + UA.
3. Add the beacon to your main bundle (fire on load, PATCH on unload).
4. Build the summary + chart endpoints (skills #2 and #3).
