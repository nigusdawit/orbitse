# URL + Objective dual-mode scraper

## When to use
You want admins to extract structured data from the open web with two complementary inputs:
- **URL mode** — they paste a specific page and the AI extracts a typed record (gallery card, pricing tier, blog draft, contact details, or a custom JSON schema).
- **Objective mode** — they describe an intent ("find competitor pricing for project-management SaaS") and let the LLM browse + summarise via its built-in web-search tool.

Same UI, same output contract, different fetch path.

## Architecture
A single `scraper.py` module exposes both modes behind a tiny API. Admin POSTs create a `scrape_jobs` row; a background worker runs the fetch + extract and writes the result back to the same row, which the UI polls.

URL-mode pipeline:
1. Parse + validate URL scheme (`http`/`https` only).
2. **SSRF guard** — resolve every host (including all redirects) through `_validate_host`. Refuse on disallowed domains, on any IP that resolves to private/loopback/link-local/multicast/reserved/unspecified, and on hosts that don't resolve at all.
3. `httpx` GET with a realistic browser User-Agent, manual redirect following (so each hop is re-validated — a `302` into `http://127.0.0.1/` would otherwise bypass the SSRF check), `_TIMEOUT_SECONDS=15`, `_MAX_REDIRECTS=5`.
4. Content-type allowlist (`text/html`, `text/plain`, `text/xml`, `application/json`, `application/xhtml+xml`, `application/xml`) — rejects images/video/binaries upfront.
5. Streaming body read capped at `_MAX_BYTES=5 MB`; reject if cap hit (don't ship half-documents to the model).
6. Clean to plain text and cap at `_CLEANED_TEXT_CAP=50_000` characters.
7. OpenAI JSON-mode call against the chosen `TARGET_SHAPES` entry; validate required fields.

Objective-mode pipeline:
1. Build a prompt from the admin's objective + chosen shape.
2. Call OpenAI Responses API with the `web_search_preview` tool.
3. Fall back to a knowledge-only answer (with a visible "no web search" note) when the tool isn't available on the configured client.

## Data model
- `scrape_jobs` — `id`, `input_mode` (`url`|`objective`), `url`, `objective`, `target_shape`, `custom_schema JSONB`, `status` (`pending`|`running`|`done`|`error`), `result_data JSONB`, `signature_hash` (used by the change-only notifier), `error_text`, `started_at`, `finished_at`, `schedule_id` (FK to `scrape_schedules` for recurring runs).
- Admin setting `scraper_disallowed_domains` (textarea, comma/newline separated; subdomain match via leading dot/`*.` normalization).

## API surface
- `POST /admin/api/scrape-jobs` — create + start (auth: `@admin_required`).
- `GET /admin/api/scrape-jobs/<id>` — poll status/result.

Programmatic (`scraper.py`):
- `fetch_url(url, disallowed_domains) -> {ok, status, content_type, body, final_url} | {ok:False, error}`
- `research_objective(client, direct_client, objective, target_shape, custom_schema) -> {ok, text, sources, ...}`
- `extract_with_ai(client, source_text, target_shape, custom_schema, source_kind) -> dict`
- `TARGET_SHAPES` — opinionated registry of supported output contracts; each entry declares `label`, `description`, `fields` (name/desc/required), `list_fields`, `push_target` (optional table for "push as draft" UX).

## Key files
- `scraper.py:313` — `fetch_url()` (the safe fetcher).
- `scraper.py:114` — `TARGET_SHAPES` registry.
- `scraper.py:229` — `_is_private_ip()` SSRF guard.
- `scraper.py:253` — `_validate_host()` re-validated on every redirect hop.
- `scraper.py:296` — `_read_capped()` streaming body cap.
- `scraper.py:935` — `research_objective()` Responses-API path.
- `app.py:35428` — `POST /admin/api/scrape-jobs` route.
- `app.py:35481` — `GET /admin/api/scrape-jobs/<id>` poll route.

## External deps
- `httpx` — stream-capable HTTP client.
- OpenAI SDK — Chat Completions in JSON mode (URL mode) + Responses API with `web_search_preview` (objective mode).
- stdlib `ipaddress`, `socket` for SSRF.

## Pitfalls
- **Always re-validate hosts on each redirect hop.** A one-shot `httpx.get(follow_redirects=True)` is a SSRF foot-gun because the final destination's host is never checked.
- **Refuse on hostnames that don't resolve at all** — silently allowing them papers over real configuration mistakes and creates inconsistent behaviour across environments.
- Don't trust `Content-Length`. Stream + cap; some servers lie or omit it.
- LLM JSON-mode is not a hard schema validator — still post-validate required fields by name. Required-field misses are how you discover schema drift.
- Custom-shape mode is the highest-risk path: an admin's JSON schema can ask for fields that don't exist on the page. Truncate input text so the model can't hallucinate freely.
- Surface SSRF refusals in plain language ("Host 'X' resolves to a private address") — admins paste internal URLs by mistake more often than you'd think.

## Adaptation notes
- Add a new shape by appending one entry to `TARGET_SHAPES` (no other code changes).
- For deeper site research, layer a small follow-link queue on top of `fetch_url` — keep the per-URL fetch the same and put the breadth limit in the queue.
- For non-AI extraction (e.g. structured JSON-LD already in the page), short-circuit the LLM call when `application/ld+json` blocks parse cleanly.
- The disallowed-domains setting is a coarse blocklist; for tenant-managed allowlists, swap the bool check for a per-tenant lookup.

## Adoption checklist
- [ ] Copy `scraper.py` and the two admin routes.
- [ ] Create the `scrape_jobs` table.
- [ ] Wire an `@admin_required` decorator and the LLM client.
- [ ] Add a disallowed-domains admin setting and pass it into every `fetch_url`.
- [ ] Decide the initial `TARGET_SHAPES` set; resist adding too many up-front.
- [ ] Add a polling UI (or SSE) for job status.
