# Developer Console (in-browser provider health probes)

**Category:** Admin Tooling
**Related:** `admin-tooling/03-preflight-checks.md`, `auth/*`

## When to use
Your app integrates a half-dozen third-party providers (OpenAI, Twilio,
Resend, ElevenLabs, ...). When something fails in production, the first
question is always "is the API key set, and does it still work?". A
"Developer" tab with one-click "Test now" probes per provider answers
that in seconds without SSH, without log spelunking, and without
burning real product quota.

## Architecture
- Two endpoints:
  - `GET /admin/api/devconsole/snapshot` — **no network calls**. Returns
    `[{name, configured}, ...]`. Opening the tab is free.
  - `POST /admin/api/devconsole/test-provider` — one network call, by
    provider name. Returns `{ok, latency_ms, error}`.
- Each probe is the cheapest possible authenticated read on that
  provider (e.g. OpenAI `GET /v1/models` is free, Yelp
  `search?limit=1`, Google Places `findplacefromtext`).
- Generic `_http_probe(method, url, headers/auth/params)` runs the
  request with an 8s timeout and turns httpx errors into the standard
  `{ok, latency_ms, error}` shape — never raises.
- **Secret redaction** is the headline feature: providers that pass
  the key in the URL (`?key=...`) would leak it if the error body
  echoes the URL back. `_collect_secrets()` pulls every secret value
  out of headers/auth/params and `_redact()` masks them in the error
  text PLUS strips the entire `?query` portion of any URL in the
  message as a belt-and-suspenders measure.
- The probe table for each provider is just a dict
  (`_PROBES = {"openai": _probe_openai, ...}`). Adding a provider is
  one function + one dict entry.

## Data model
None. Stateless — every probe runs live.

## API surface
- `GET /admin/api/devconsole/snapshot` (`app.py:25006`)
- `POST /admin/api/devconsole/test-provider`
  body `{name: "openai"}` (`app.py:25053`)

Per-provider configured-detection is in `devconsole._is_configured(name)`
which knows about Replit Connector aliases (e.g.
`AI_INTEGRATIONS_OPENAI_API_KEY`).

## Key files
- `devconsole.py` — all probes, all redaction, the `PROVIDERS` ordered
  list
- `devconsole.py:_http_probe` — generic timed request
- `devconsole.py:_redact`, `_collect_secrets` — leak prevention
- `app.py:25006` — snapshot route
- `app.py:25053` — test-provider route
- `templates/admin/dashboard.html` — "Developer" tab UI

## External deps
- `httpx` for the probes (any HTTP client works).
- Whatever providers you probe. Each probe is ~10 lines.

## Pitfalls
- **Don't run probes on tab open** — operators will leave the tab
  open and you'll DOS your own quota. Only run on explicit button click.
- **Always set a timeout** (this template uses 8s). A hung TCP
  connection should not hang the admin UI.
- **Always redact**. Even providers using header-auth can leak the
  token if the response body quotes the request back at you.
- **Probes must never raise** — wrap them in try/except and return the
  error as a string. A 500 in the dev console is a usability bug.
- **Configured ≠ working** — a probe failure with a configured key
  usually means quota exhausted or key revoked, not unset.

## Adaptation notes
- For non-HTTP providers (DB, Redis, S3), the same shape works — swap
  `_http_probe` for a custom timed call.
- Add a probe history table (`probe_results: name, ok, latency_ms,
  error, ts`) and chart latency over time for a poor man's status page.
- Expose `/healthz?provider=openai` for external uptime monitors.
- For multi-tenant SaaS, scope `_is_configured` to the tenant's stored
  keys instead of `os.environ`.

## Adoption checklist
1. Create `devconsole.py` with a `PROVIDERS` list, an `_is_configured`
   function, and one `_probe_*` per provider.
2. Use a generic `_http_probe` for shared timing/redaction logic.
3. Add the two routes, both gated by `@admin_required`.
4. Build the UI: one row per provider with a green/red dot
   (configured) and a "Test now" button → latency + error display.
5. Audit-log probe button clicks (cheap; helps catch a noisy admin
   accidentally hammering a provider).
