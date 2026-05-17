# UTM + Device + Referrer Metadata Pipeline

**Category:** Forms
**Related:** `forms/01-dynamic-form-builder.md`, `forms/02-partial-abandon-capture.md`, Analytics module (Batch 7)

## When to use
You want every form submission (and every partial save) to carry enough marketing/attribution context that the operator can answer "where did this lead come from?" without bolting on a separate analytics system — UTM tags from the landing URL, device/browser/OS for follow-up channel choice, referring page for organic attribution, and the session id used to join with page views and prior partials.

## Architecture
- **Capture happens at the edge.** The frontend submit/partial handler reads:
  - UTM params from `location.search` (cached at first page load into `sessionStorage` so they survive intra-site navigation)
  - `document.referrer` for the referring URL
  - `navigator.language`, `screen.width x screen.height`
  - `session_id` (UUID from `sessionStorage`)
  Then POSTs all of this alongside the form payload.
- **Server enrichment.** The server takes:
  - `User-Agent` header → cheap regex parse into `browser` (Chrome/Firefox/Safari/Edge/MSIE) and `os` (Windows/Mac/Linux/Android/iOS) via `_parse_ua()`
  - Client IP (from `request.remote_addr`, honoring proxy headers via ProxyFix)
  - The `User-Agent` string itself (kept raw for forensic / better-parser later)
- **Wide, denormalized columns** on `form_submissions`. No JSONB for this — every analytics query wants to GROUP BY on these fields, so they're indexed first-class columns.
- **No external UA parser.** A 10-line `in`-check regex catches ~95% of real traffic and adds zero dependency. If you need granular OS versions / mobile device models, swap in `ua-parser-js` (client) or `user-agents` (server) later — the column shape doesn't change.

## Data model
Columns on `form_submissions` (`app.py:~1303`), beyond the form data itself:

| Column | Source |
|---|---|
| `session_id` | Client `sessionStorage` UUID |
| `utm_source` | `?utm_source=` |
| `utm_medium` | `?utm_medium=` |
| `utm_campaign` | `?utm_campaign=` |
| `utm_term` | `?utm_term=` |
| `utm_content` | `?utm_content=` |
| `page_url` | `location.href` at submit time |
| `referrer_url` | `document.referrer` |
| `language` | `navigator.language` |
| `screen_resolution` | `<w>x<h>` |
| `ip_address` | `request.remote_addr` (post-ProxyFix) |
| `user_agent` | Raw UA string (truncated to a reasonable cap) |
| `browser` | Parsed by `_parse_ua` |
| `os` | Parsed by `_parse_ua` |
| `submission_data` JSONB | The actual form payload |

`session_id` is the join key for joining a submission back to the visitor's page views (if you also have an analytics module that records page views by `session_id`).

## API surface
- `POST /api/forms/<slug>/submit` (`app.py:~27115`) — captures all the above plus runs validation
- `POST /api/forms/<slug>/partial` (`app.py:~27018`) — same capture, no validation

Both accept the metadata fields at the top level of the JSON body. The server treats absence as `NULL` — don't reject submissions that lack metadata (older bookmarks, JS-disabled browsers, weird privacy plugins).

## Key files
- `app.py:~1303` — `form_submissions` DDL with the metadata columns
- `app.py:~26952` — `_parse_ua(user_agent_string) -> (browser, os)`
- `app.py:~27115` — submit handler that wires it all together
- `public/script.js` — client-side capture (search `utm_source` or `sessionStorage`)

## External dependencies
None — pure stdlib regex + Postgres.

## Pitfalls
- **UTM persistence across navigation.** A visitor lands on `/landing?utm_source=google`, clicks through to `/contact`, fills the form — by then `location.search` is empty. Cache UTMs in `sessionStorage` on first load and re-read them at submit. (The current code does this — verify before refactoring.)
- **Referrer is unreliable.** Modern browsers strip it on HTTPS→HTTPS cross-origin nav by default. `Referrer-Policy: no-referrer-when-downgrade` on your own pages helps for inbound; nothing you do helps for cross-site.
- **`screen_resolution` is the physical screen, not the viewport.** A mobile visitor with a 412×915 viewport reports 1080×2340. Either store both or rename to make it clear.
- **IP address is PII in EU jurisdictions.** Hash it or truncate the last octet (`192.168.1.0`) before storing if you want to be GDPR-clean.
- **`_parse_ua` is intentionally crude.** It will mis-classify some less-common combinations (e.g. Edge sometimes contains "Chrome" in its UA string — order the checks Edge-first). Document the trade-off; don't add a real UA parser unless analytics demands it.
- **`session_id` is client-supplied** — a malicious client can spoof it to merge into someone else's session. Treat it as a join hint, never as an auth boundary.
- **Bots fill the table** with noise. Add a `bot_score` column populated by a cheap heuristic (no JS-only field set, UA contains `bot|spider|crawler`) and filter analytics on `bot_score < threshold`.

## Adaptation notes
- For multi-touch attribution (which UTM first brought this visitor, which one closed?), record UTMs in BOTH the first page view AND each submission, then have the analytics layer pick the model (first-touch / last-touch / linear).
- For server-side click-id capture (gclid, fbclid), add `gclid` / `fbclid` columns alongside the UTMs and capture from the same `location.search` parse.
- The same metadata block is reused by `service_bookings` partial-saves and final bookings (skill `booking/04`) — keep the field names identical across surfaces so the analytics view can `UNION` them.
- To downstream this into a real warehouse, a single `COPY (SELECT ...) TO STDOUT WITH CSV` of the table gives you everything you need; the columns are flat and stable.
