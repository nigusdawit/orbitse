# Aggregate reviews snapshot (Google / Yelp / TripAdvisor)

## When to use
You want to display "4.8★ from 312 reviews on Google" badges on your public site, but **don't** want to:
- hit external review APIs on every visitor request,
- pay the per-call fee on every page view,
- have the site break when the provider rate-limits you.

A nightly snapshot per (destination, provider) cached in your DB solves all three.

## Architecture
Two tables and one scheduler tick:

- `review_destinations` — one row per business location/listing the operator wants tracked, with provider IDs (Google place_id, Yelp business alias, TripAdvisor location_id) and a `public_visible` flag for whether to expose this destination on the public API.
- `external_reviews` — append-or-upsert per `(destination_id, provider)` with `total_count`, `avg_rating`, `snapshot_at`, full `raw_json`, and `error_text` for the last attempt.

A daily tick (`_review_collector_tick`, every 24 h) calls `_refresh_all_external_reviews` which loops through destinations and fetches each enabled provider in turn:
- Google Places (`GOOGLE_PLACES_API_KEY`) — `place details` endpoint, picks `user_ratings_total` + `rating`.
- Yelp Fusion (`YELP_API_KEY`) — business endpoint, picks `review_count` + `rating`.
- TripAdvisor Content (`TRIPADVISOR_API_KEY`) — location endpoint, picks `num_reviews` + `rating`.

Each provider call is wrapped in try/except; failures land in `error_text` on the snapshot row instead of bubbling up — partial freshness is better than nothing.

The public API exposes only destinations with `public_visible=TRUE`:
- Counts are clamped to non-negative.
- Average ratings rounded to one decimal.
- Stale snapshots (>48 h) are still returned but flagged so the frontend can choose to hide them.

Providers gated by per-key presence: if `YELP_API_KEY` is absent, those calls are skipped entirely with a clear log line — no fake-zero rows.

## Data model
- `review_destinations` — `id`, `name`, `kind` (`google`|`yelp`|`tripadvisor`|`internal`), `url`, `external_id` (place_id / alias / location_id), `public_visible BOOLEAN`.
- `external_reviews` — `id`, `destination_id FK`, `provider`, `total_count INT`, `avg_rating NUMERIC(3,2)`, `snapshot_at TIMESTAMPTZ`, `raw_json JSONB`, `error_text TEXT NULL`. `UNIQUE(destination_id, provider)` for upserts.

## API surface
- `GET /api/review-snapshots` — public read of the snapshot table, filtered to `public_visible=TRUE`. Returns `[{destination, provider, total, avg, snapshot_at, stale}]`.
- Admin CRUD on `review_destinations` (standard `/admin/api/review-destinations/...`).
- Admin "Refresh now" button calls `_refresh_all_external_reviews()` ad-hoc.

## Key files
- `app.py:36825` — `_refresh_all_external_reviews()` provider loop.
- `app.py:36837` — `_review_collector_tick()` daily fire.
- `app.py:37415` — `GET /api/review-snapshots` public endpoint.

## External deps
Env-keyed (each independently optional):
- `GOOGLE_PLACES_API_KEY` — Google Places API (Place Details).
- `YELP_API_KEY` — Yelp Fusion API.
- `TRIPADVISOR_API_KEY` — TripAdvisor Content API.

## Pitfalls
- **Each provider has its own field names.** Don't trust documentation alone — log `raw_json` and verify before parsing. Yelp returns `review_count`, Google returns `user_ratings_total`, TripAdvisor returns `num_reviews`.
- Rate limits are aggressive on TripAdvisor in particular — daily is usually fine, but if you want hourly, add a per-provider throttle.
- Google Places billing: Place Details is one of the more expensive endpoints. Use `fields=rating,user_ratings_total` to minimise the SKU charge per call.
- Don't expose `raw_json` on the public API — it can include internal IDs / quota counters.
- Treat a 0-review listing as a real datum (don't filter it away), but DO flag a `null` (never-fetched) snapshot separately on the public response so the frontend can hide it.
- For destinations that match multiple providers, render them as a combined "rating across X reviews on Google + Yelp" badge by aggregating client-side — server-side aggregation hides the per-provider breakdown the admin needs.

## Adaptation notes
- Add Facebook Pages (Graph API) and Trustpilot the same way — new column on `review_destinations.kind`, new branch in the refresh loop.
- For very frequent refresh needs, swap the daily tick for a per-destination `next_refresh_at` column and a fan-out worker.
- Surface "review count grew by N since last ask" by joining `external_reviews` against `review_requests.sent_at` (a queued follow-up task).
- Persist a small ring of historical snapshots (e.g. last 30 days) by changing the upsert to an append-with-window-retention, enabling trend lines.

## Adoption checklist
- [ ] Create the two tables and seed at least one destination.
- [ ] Set the env keys you intend to use; verify `render_provider_status`-style helpers for each.
- [ ] Register the daily tick with your scheduler hub.
- [ ] Add admin CRUD and a "Refresh now" button.
- [ ] Build the public endpoint; clamp counts, round ratings, mark staleness.
- [ ] Never expose `raw_json` publicly.
