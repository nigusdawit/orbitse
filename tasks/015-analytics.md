# Task 015 — M15: analytics (pageviews + dashboards)

## Goal
Visitor + chat + form analytics (absent today).

## Acceptance criteria
- [ ] Schema: `page_views` (session/visitor, url, referrer, UTM, device/browser/
      os, screen, language, duration).
- [ ] Public tracking: `POST /api/track/pageview` (rate-limited per session+page)
      + `POST /api/track/duration` (sendBeacon). Embeddable (X-Embed-Key aware).
- [ ] Admin: `GET /admin/api/analytics` (views, uniques, top pages, referrers,
      UTM, device/browser/os) + `/analytics/chart` (daily, 30d). Chat analytics
      (per-turn tool usage from `tool_calls_json`) + form analytics views.
- [ ] Widget/loader fires pageview tracking.

## Test requirements
- Gate: track a pageview + duration; analytics aggregation returns expected
  counts; rate-limit on repeat pageview within window.

## Dependencies: none   ## Status: not_started   ## Branch: task/015-analytics
