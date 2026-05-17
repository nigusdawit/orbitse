# Public-API Cache Headers (Allowlist + 6 Defense Layers)

## When to use
Your app has anonymous read endpoints whose content changes minutes-to-days apart (site settings, blog index, product list, marketing copy). Without cache headers every page-load re-fetches them, your origin gets hammered, and putting a CDN in front buys you nothing because the CDN obediently respects "no headers = don't share." You want fresh-feeling content for admins while letting a CDN collapse anonymous traffic to one origin hit per minute.

## Architecture
A single Flask `after_request` hook decides whether to stamp `Cache-Control: public, max-age=60, stale-while-revalidate=300` on the response. It bails on any of six conditions, in priority order:

1. **Method ≠ GET** — writes are obviously not cacheable.
2. **Status ≠ 200** — never cache 4xx/5xx/redirects; they should re-evaluate.
3. **Path not in the allowlist** — a hardcoded `frozenset` of well-known anonymous reads. Allowlist (not denylist) because the blast radius of forgetting to add a new endpoint is "missed perf win"; the blast radius of forgetting to exclude is "leaked private data to a CDN."
4. **Response already has `Cache-Control`** — respect endpoints that set their own policy (SSE streams set `no-cache`, TTS prepare sets `no-store`).
5. **Response has `Set-Cookie`** — caching `public` would let a CDN replay one user's session cookie to other clients.
6. **Request carries the Flask session cookie** — an admin *might* be logged in; serve them uncached so their edits show up instantly.

Critical subtlety in (6): you must check `request.cookies` directly. Calling `session.get(...)` triggers Flask's session interface, which sets `Vary: Cookie` on the response. That fragments the shared CDN cache across every distinct cookie value clients send (analytics, locale, A/B buckets) and destroys ~all of the benefit.

`max-age=60` + `stale-while-revalidate=300` means: a refresh within 60s is instant from cache; between 60s and 360s the cached copy is served instantly *and* revalidated silently in the background. Users never wait on a stale-cache miss.

## Data model
None.

## API surface
Pure HTTP. The allowlist is a module-level `frozenset[str]` of exact paths.

## Key files
- `app.py` — `_CACHEABLE_API_PATHS` (~line 223) and the `_add_public_api_cache_headers` `after_request` hook.

## External deps
None at the framework level. To realize the gain, you need a CDN (Cloudflare, Fastly, CloudFront) sitting in front of the origin and respecting `Cache-Control: public`.

## Pitfalls
- **Reading `session` accidentally adds `Vary: Cookie`.** Always inspect `request.cookies` for the session cookie name; never `session.get(...)`.
- **An admin edits → readers see stale data for up to 60s.** That's the trade. Drop `max-age` if your business can't tolerate it; admins themselves are exempt via condition 6 so *they* always see fresh.
- **Allowlist drift.** Every new public read endpoint must be added by hand. Compensate with a comment in the route handler ("public-cacheable: add to `_CACHEABLE_API_PATHS`") and an audit script if you grow past ~30 paths.
- **`public` + auth = leak.** Conditions 5 and 6 exist exactly to prevent this. Never relax them.
- **Personalized endpoints accidentally allowlisted** would serve user A's content to user B from the CDN. Audit the allowlist when adding anything that branches on identity.

## Adaptation notes
- Different freshness tiers: a second `_VERY_CACHEABLE` set for truly static stuff (legal text, logo) at `max-age=86400, stale-while-revalidate=604800`.
- For personalized-but-cacheable responses, use `Cache-Control: private, max-age=60` (browser cache only, not CDN).
- Pair with ETag/Last-Modified for revalidation-as-304 wins. Flask doesn't add these automatically; you'd hash the response body or stamp from the underlying row's `updated_at`.

## Adoption checklist
- [ ] Catalog the truly-anonymous read endpoints. Be ruthless — if it ever varies by user, it's out.
- [ ] Add them to `_CACHEABLE_API_PATHS`.
- [ ] Wire the `after_request` hook, preserving all six bail conditions.
- [ ] Verify with `curl -I` that allowlisted endpoints get `Cache-Control` and the rest don't.
- [ ] Verify a logged-in admin's responses do NOT carry `Cache-Control` (the session cookie check works).
- [ ] Verify `Vary: Cookie` is NOT in the response (means you accidentally read `session`).
- [ ] Put a CDN in front and confirm cache hit ratio rises.
