# Tokenised review short-link (click + convert tracking)

## When to use
You want every review-ask email/SMS to carry a per-recipient short URL like `/r/abc123` that:
- looks short enough for an SMS body,
- redirects the user to the right review form/destination,
- records `clicked_at` on click,
- records `converted_at` when the corresponding form is submitted,

so you can compute a real funnel (sent → clicked → converted) per channel/template/destination.

## Architecture
Reuses the messaging tokenised short-link pattern (see Messaging catalog → tokenised short-links skill) for the URL shape, but binds the token to a `review_requests` row so the funnel metrics are review-specific.

Mint:
- When `_create_review_request()` is called, generate `short_token = secrets.token_urlsafe(12)` and store on the row.
- The rendered email/SMS body links to `/r/<short_token>` instead of the destination URL directly.

Click:
- `GET /r/<token>` looks up the request, sets `clicked_at = NOW()` (only on first click — guarded), increments a click counter if you want a histogram, then 302-redirects to either:
  - the external review URL (`review_destinations.url` for Google/Yelp/TripAdvisor), or
  - the internal review form, with `?r=<token>` appended so the convert step can correlate.

Convert:
- For internal forms (`review_destinations.kind='internal'`), the form-submit handler reads `request.args.get("r")` (or `request.form.get("review_token")`), looks up the row, and sets `converted_at = NOW()`. Only internal forms can convert — there's no callback from Google.
- For external destinations, "click" is the strongest signal you can get; treat it as the funnel terminus.

Funnel widget on the admin dashboard joins the three timestamps to compute per-template / per-channel conversion rates.

## Data model
On `review_requests`:
- `short_token TEXT UNIQUE NOT NULL`
- `clicked_at TIMESTAMPTZ NULL`
- `converted_at TIMESTAMPTZ NULL`
- (optional) `click_count INT DEFAULT 0`

## API surface
- `GET /r/<token>` — public click-through redirect.
- `POST /api/forms/submit` — existing public form submit; gains a 2-line check for `r` query param + matching token to set `converted_at`.
- Admin reads via `/admin/api/reviews/requests` show the funnel timestamps.

## Key files
- `app.py:37377` — `GET /r/<token>` handler (click).
- `app.py:27233` — `/api/forms/submit` route.
- `app.py:27255` — `converted_at` write on internal-destination match.

## External deps
None — pure stdlib (`secrets.token_urlsafe`) for token generation.

## Pitfalls
- **Don't reuse a single shared short-link table across messaging + reviews unless you're willing to share the funnel definition too.** Keeping `short_token` per-domain (one column on `review_requests`, another on `outbound_messages`) is simpler and lets each domain evolve its own analytics.
- Tokens must be long enough to resist enumeration — `secrets.token_urlsafe(12)` is ~16 chars of base64, plenty for non-secret use.
- Set `clicked_at` only on the FIRST click (`COALESCE(clicked_at, NOW())` in the UPDATE) so repeat clicks don't reset the metric.
- Robots and link-preview bots (Gmail, iMessage, Slack) will follow your short link the moment the message lands, inflating click numbers. Mitigations: check User-Agent against a known bot list and skip the timestamp write; or accept the bias and document it for the admin.
- The redirect target must be validated. If `review_destinations.url` is admin-editable, treat the URL as untrusted and refuse non-`http(s)` schemes before issuing the 302.
- Token lookup happens on a public route — make sure the index on `short_token` is unique and used (`EXPLAIN` your query).

## Adaptation notes
- For external destinations that DO have a callback (e.g. Google's review API via an OAuth integration), promote the click→convert step the same way internal forms do.
- Add a `clicks_log` table (`token`, `clicked_at`, `user_agent`, `ip`) if you want a histogram instead of a single timestamp.
- Pair with a transactional bot-filter by emitting a JS pixel on click and only counting tokens that also fire the pixel — defeats simple link-preview bots.
- The same pattern works for any "ask + measure" flow: surveys, NPS prompts, magic-link sign-ins.

## Adoption checklist
- [ ] Add `short_token`, `clicked_at`, `converted_at` columns to `review_requests`.
- [ ] Generate `secrets.token_urlsafe(12)` at request creation, store unique.
- [ ] Implement `GET /r/<token>` with a first-click-only timestamp write + safe 302.
- [ ] Append `?r=<token>` to internal redirect URLs; have the form-submit handler honour it.
- [ ] Build the funnel widget joining `sent_at / clicked_at / converted_at`.
- [ ] Decide your stance on link-preview bots and document it.
