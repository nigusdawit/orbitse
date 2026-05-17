# Device / Browser / OS / Referrer Breakdown

**Category:** Analytics
**Related:** `analytics/01-first-party-page-view-tracker.md`, `analytics/03-chartjs-admin-dashboards.md`, `forms/04-utm-device-metadata-pipeline.md`

## When to use
You already collect page views (skill #1) or form submissions
(`forms/04`) and you want the admin to see "what fraction of my traffic is
mobile / Safari / iOS" and "where are visitors coming from" without pulling
in a heavy UA-parsing library (`user-agents`, `ua-parser-js`).

## Architecture
- A tiny regex-based UA parser (`_parse_ua` in `app.py:~26989`) extracts
  three buckets: browser, os, device_type.
- The parser is intentionally coarse — it categorises into ~5 browsers
  (Chrome, Safari, Firefox, Edge, Other), ~5 OSes (iOS, Android, macOS,
  Windows, Linux/Other), and 3 device types (mobile, tablet, desktop).
  That's enough for a pie chart and avoids the maintenance cost of a full
  UA database.
- Called once per row insert in the analytics ingest path AND once per
  form submission (`forms/04`) so both surfaces share the same dimensions.
- Referrer breakdown is computed by `GROUP BY` on `referrer_url`'s host
  portion in the summary endpoint.

## Data model
Reuses the `page_views` table from skill #1. Adds no new columns beyond
the three the parser fills: `browser`, `os`, `device_type`.

Optionally precompute a `referrer_host` column (or generated column) so
"top referrers" is an index scan:
```sql
ALTER TABLE page_views
ADD COLUMN referrer_host TEXT GENERATED ALWAYS AS
  (split_part(split_part(referrer_url, '://', 2), '/', 1)) STORED;
CREATE INDEX ON page_views (referrer_host);
```

## API surface
- `GET /admin/api/analytics` — returns aggregate stats including
  per-browser / per-OS / per-device-type counts and top referrers
  (`app.py:27388`).
- Optional `?since=YYYY-MM-DD&until=YYYY-MM-DD` filters.

Response shape (typical):
```
{
  "total_views": 12345,
  "unique_visitors": 4321,
  "by_browser":  [{"key":"Chrome","count":5000}, ...],
  "by_os":       [{"key":"iOS","count":3000}, ...],
  "by_device":   [{"key":"mobile","count":7000}, ...],
  "top_referrers":[{"key":"google.com","count":900}, ...],
  "top_pages":   [{"key":"/","count":4500}, ...]
}
```

## Key files
- `app.py:~26989` — `_parse_ua(ua_string) -> (browser, os, device_type)`
- `app.py:27316` — ingest call site that invokes `_parse_ua`
- `app.py:27388` — summary endpoint with `GROUP BY` aggregations
- Form-submission call site (see `forms/04`) — same parser, different table

## External deps
None. Pure regex over `User-Agent` string.

## Pitfalls
- UA strings lie. Treat the buckets as approximate, not authoritative.
  Don't use them for access control.
- Modern Chromium has "User-Agent reduction" — the version digits are
  frozen, but browser/os family detection still works.
- A "bot" bucket is worth adding. Match common crawler tokens
  (`bot`, `crawl`, `spider`, `headless`) and exclude them from "real
  visitor" metrics.
- Referrer URLs are unreliable: many browsers strip them on HTTPS→HTTP
  hops, and some privacy modes blank them entirely. Always have a
  "(direct)" bucket for empty referrers.

## Adaptation notes
- If you need precise versions (e.g. "Chrome 119 vs 120 share"), swap
  the regex for `ua-parser-js` (frontend) or `python-user-agents`
  (backend). The shape of the dashboard doesn't change.
- For mobile vs tablet split, the heuristic is "iPad / large Android +
  no Mobile token = tablet". Test against your real traffic.
- Add `country` to the breakdown by joining MaxMind's GeoLite2 CSV
  against `ip_address` in a nightly job.

## Adoption checklist
1. Add `_parse_ua` to your project (~30 lines of regex).
2. Call it server-side in your ingest path (don't trust client-sent
   browser/os fields).
3. Add a bot filter.
4. Build the summary endpoint with `GROUP BY` queries.
5. Wire each bucket array into a Chart.js donut (see skill #3).
