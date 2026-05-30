# Task 015 — M15: analytics (pageviews + dashboards)

## Goal
Visitor + chat + form analytics (absent today).

## Acceptance criteria
- [x] Schema: `page_views` (session/visitor, url, path, referrer, UTM, device/
      browser/os, screen, language, duration_ms).
- [x] Public tracking: `POST /api/track/pageview` (deduped per session+path
      within a window) + `POST /api/track/duration` (sendBeacon). Embeddable
      (in EMBEDDABLE_PREFIXES, X-Embed-Key aware, tenant-scoped via g.tenant_id).
- [x] Admin: `GET /admin/api/analytics` (views, uniques, top pages, referrers,
      UTM, device/browser/os) + `/analytics/chart` (daily, 30d) + `/analytics/
      chat` (per-tool usage from `tool_calls_json`) + `/analytics/forms`.
- [x] Loader fires pageview on load + duration beacon on pagehide.

## Test requirements
- Gate: track a pageview + duration; analytics aggregation returns expected
  counts; rate-limit on repeat pageview within window.

## Dependencies: none   ## Status: done   ## Branch: task/015-analytics

## Notes
Merged to main (--no-ff). Gate: 289/289 incl. pageview track + path/UTM/UA
parse, per-(session,path) dedupe window, duration beacon patch, summary
aggregations (views/sessions/top-pages), chart series, chat tool_usage, forms,
and admin-auth gating. Unit: `test_analytics.py` pins the UA parser (iOS-before-
macOS ordering, Edge-over-Chrome). Fixed: forms query referenced `created_at`
(form_submissions uses `submitted_at`); UA OS detection reordered so iPhone/iPad
("...like Mac OS X") classify as iOS, not macOS. Rate-limit implemented as a
dedupe window (in-process); a Postgres-backed variant can layer on rate_buckets
if cross-worker dedupe is needed.
