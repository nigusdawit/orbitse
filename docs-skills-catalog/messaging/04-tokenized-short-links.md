# Tokenized Short-Link Tracking (`/r/<token>`)

**Category:** Messaging
**Related:** `messaging/01-unified-send-helper.md`, Reviews module (Batch 10)

## When to use
You sent an outbound email or SMS that contains a call-to-action link, and you want to know (a) whether the recipient clicked it and (b) whether that click led to the goal action (form submit, purchase, RSVP). Per-recipient unique tokens give you both signals without depending on the email provider's link-rewriting feature, and they work identically for SMS — where the provider has no click tracking at all.

## Architecture
- **Per-outbound-message token.** When you create the outbound row (review request, campaign send, etc.), generate a short random `short_token` and embed `https://<site>/r/<token>` in the message body.
- **Click endpoint** `GET /r/<token>` looks up the token, stamps `clicked_at = now()` (only if NULL — first click wins) and increments `click_count`, then 302-redirects to the row's destination URL.
- **Conversion endpoint** is whatever form/RSVP/checkout the recipient lands on — it accepts `?r=<token>` as a query param, and on successful submission stamps `converted_at = now()` on the matching row.
- **One row per outbound asks**, not one row per token type. Reuse the same table for review-asks, win-back campaigns, abandoned-cart nudges — just discriminate with a `channel` or `source_kind` column.

## Data model
This project's first user of the pattern is **review requests**. Table `review_requests` (`app.py:~2872`):

| Column | Purpose |
|---|---|
| `id` SERIAL PK | |
| `destination_id` FK | Which business / location the ask is about |
| `channel` | `'email'` or `'sms'` |
| `recipient_name`, `recipient_email`, `recipient_phone` | |
| `purchased_item` | Human-readable "what they bought" for AI message drafting |
| `source_kind`, `source_id` | Polymorphic FK back to the order / RSVP that triggered the ask |
| `status` | `pending` → `sent` → (`clicked` \| `converted` \| `bounced`) |
| `short_token` | URL-safe random string, UNIQUE |
| `subject_snapshot`, `body_snapshot` | Post-merge-tag message content |
| `error_text` | |
| `send_at` | Schedule the ask for N days after fulfillment |
| `sent_at`, `clicked_at`, `converted_at` | Stamped by send / `/r/<token>` / form-submit |
| `click_count` | |
| `created_at` | |

## API surface
- `GET /r/<token>` — public click handler (`app.py:~37369`). Always 302s to the destination even if the token is unknown (don't leak token validity to scrapers); just don't stamp anything in that case.
- Conversion is captured by reading `?r=<token>` on any goal endpoint and stamping `converted_at` on the matching `review_requests` row. In this codebase, the wiring lives in the Review Collector module rather than in the generic form submit handler — the generic form submit endpoint is the natural place to extend, but conversion attribution is not coupled to it by default.

## Key files
- `app.py:~2872` — `review_requests` DDL
- `app.py:~37369` — `/r/<token>` redirect handler
- Review Collector module — owns the `converted_at` stamp; the generic `POST /api/forms/<slug>/submit` (`app.py:~27115`) does NOT stamp it today, so add a `?r=<token>` handler there if you want submissions to attribute

## External dependencies
None — pure Postgres + Flask.

## Pitfalls
- **Token entropy matters.** `secrets.token_urlsafe(12)` (≥96 bits) is plenty; anything shorter is brute-forceable for an attacker who wants to fake conversions.
- **`clicked_at` must be set only on first click**, otherwise a recipient who clicks twice resets the timeline. Use `UPDATE ... WHERE clicked_at IS NULL` and increment the count separately.
- **Always 302 even on miss.** A 404 on `/r/<bad>` tells scrapers and competitors which tokens are alive. Redirect to the homepage instead.
- **Email clients pre-fetch links** (Outlook Safe Links, Gmail proxy). The first "click" may be the security scanner, not the human. If accuracy matters, deduplicate by user-agent or add a 5-second JS-required interstitial — accepting that some real clicks will be lost.
- **Conversion attribution is last-touch only.** A recipient who clicks the ask, browses for two days, then converts without the token in the URL won't be attributed. To fix, drop a cookie on `/r/<token>` and check it in the conversion handler.

## Adaptation notes
- To use the same table for review-asks AND win-back campaigns AND referral codes, generalize the table name (`tracked_links`) and use `source_kind` to discriminate. Keep `destination_id` polymorphic with `(source_kind, source_id)` instead of a typed FK.
- For a global "share" link (one URL, many recipients) instead of per-recipient tokens, drop `recipient_*` columns and treat each click as an anonymous event in a separate `tracked_link_clicks` table.
- To shorten further, base62-encode an auto-increment id instead of using a random token. Faster to type into SMS but reveals send volume.
- To support QR codes (print → web attribution), the same `/r/<token>` URL goes straight into a QR generator — no code change needed.
