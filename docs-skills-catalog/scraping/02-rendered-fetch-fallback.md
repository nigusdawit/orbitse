# Rendered-fetch fallback (headless browser for SPA pages)

## When to use
Many modern marketing, booking, and storefront sites are React/Vue SPAs that ship an empty HTML shell and assemble all visible content client-side. A plain HTTP GET returns ~50 chars of `<div id="app">`. Without a JS-execution step, your scraper sees nothing useful.

You want an opt-in retry path that delegates the GET to a hosted headless-browser service (no Node/Playwright in your stack) when the plain fetch comes back suspiciously empty, while keeping every SSRF + size + content-type guard on the *target* URL.

## Architecture
A second fetcher (`fetch_url_rendered`) wraps the plain `fetch_url` flow but swaps the actual HTTP request for a call to a hosted provider. Two providers are supported, selected by env:

- **ScrapingBee** — `GET https://app.scrapingbee.com/api/v1/?api_key=…&url=…` (default; needs `SCRAPINGBEE_API_KEY`).
- **Browserless** — `POST {BROWSERLESS_URL}/content?token=…` with `{"url": …}` (needs `BROWSERLESS_TOKEN`; `BROWSERLESS_URL` defaults to `https://chrome.browserless.io`).

The target URL is SSRF-validated **before** being handed to the provider (same `_validate_host` rules — no shortcut). The response is still subject to the same `_MAX_BYTES` cap and content-type allowlist; only the GET itself is delegated. Timeout is bumped to `_RENDER_TIMEOUT_SECONDS=45` to absorb browser launch + JS run.

Three trigger paths:
1. **Manual opt-in** — admin flips "Use rendered fetch" (setting `scraper_render_enabled`) before launching the job.
2. **Auto-fallback hint** — when a plain fetch returns cleaned text shorter than `_JS_ONLY_HINT_THRESHOLD=120` chars, the UI surfaces a "looks like a JS-only page — try rendered fetch?" prompt.
3. **Status surfacing** — `render_provider_status()` returns `{configured, provider, reason}` so the admin settings panel can show a coloured badge ("ScrapingBee configured ✓" / "Set SCRAPINGBEE_API_KEY to enable").

## Data model
None new — the same `scrape_jobs` row stores the result.

## API surface
Programmatic (`scraper.py`):
- `fetch_url_rendered(url, disallowed_domains) -> same dict shape as fetch_url`.
- `render_provider_status() -> {configured, provider, reason}`.

Env vars:
- `SCRAPER_RENDER_PROVIDER` — `scrapingbee` (default) or `browserless`.
- `SCRAPINGBEE_API_KEY` — required for ScrapingBee.
- `BROWSERLESS_TOKEN` — required for Browserless.
- `BROWSERLESS_URL` — Browserless endpoint (defaults to hosted SaaS).

UI: admin "Web Scraper" tab → "Use rendered fetch" checkbox + provider status badge.

## Key files
- `scraper.py:101` — `_JS_ONLY_HINT_THRESHOLD` constant.
- `scraper.py:465` — `_RENDER_TIMEOUT_SECONDS` constant.
- `scraper.py:468` — `_render_provider_config()` env resolver.
- `scraper.py:525` — `fetch_url_rendered()` main entry.
- `templates/admin/dashboard.html:20731` — admin toggle for `scraper_render_enabled`.

## External deps
- A hosted rendering provider account (ScrapingBee or Browserless).
- `httpx` (already used by the plain fetcher).

## Pitfalls
- **Always re-run SSRF validation on the target URL** before handing it to the provider. The provider will happily fetch `http://10.0.0.1/` for you if you let it.
- Don't relax the content-type allowlist for the rendered path — providers can be tricked into returning binary attachments.
- Cost: rendered fetches are ~50–500× more expensive per call than a plain GET. Default to plain; only escalate on the threshold trigger or explicit admin opt-in.
- Most provider failures are "rendering took too long" (HTTP 504) or "site blocked us". Surface the provider's error string verbatim — admins find it useful.
- Don't cache the rendered result by URL alone — many SPAs vary content by cookie/query/locale. Cache by `(url, render_provider)` if you cache at all; safer to skip caching v1.
- `render_provider_status()` must NEVER raise — the admin settings page will show it on every load.

## Adaptation notes
- Add a third provider (Bright Data, Apify, Zenrows) by extending `_render_provider_config` with another branch.
- For self-hosted Playwright, point `BROWSERLESS_URL` at your own instance — the same `/content` API works.
- For long-running pages, switch to ScrapingBee's `wait_for` / `js_scenario` extensions by adding optional query params.
- The 120-char auto-fallback threshold is conservative; tune up to ~400 if you scrape lots of legitimately-short pages.

## Adoption checklist
- [ ] Sign up for ScrapingBee or Browserless and set the env vars.
- [ ] Add the "Use rendered fetch" admin toggle and a `scraper_render_enabled` setting.
- [ ] Wire `render_provider_status()` into the admin settings page (coloured badge).
- [ ] Surface the auto-fallback hint when cleaned text < 120 chars.
- [ ] Confirm SSRF validation runs on the target URL **before** the provider call.
- [ ] Bump request timeout to 45 s for the rendered path.
