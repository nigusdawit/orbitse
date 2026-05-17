# Stripe Product / Price Sync Engine (one-way, local → Stripe)

**Category:** Payments · Catalog
**Status:** Production

## When to use
You keep a local `products` table that the admin edits in your own
dashboard, but Checkout still needs Stripe `Product` + `Price`
objects to charge against. You want the local table to be the source
of truth: edit name/description/image → Stripe updates; change the
price → a new Stripe Price is created and the old one is retired
without breaking any in-flight Checkout Sessions. You also want
test mode and live mode to maintain independent Stripe catalogs so
flipping between them doesn't accidentally show test items as live.

## Architecture
- A mapping table `stripe_product_sync` keyed by
  `(local_product_id, mode)` stores the Stripe `Product.id`,
  `Price.id`, the cents/currency that Price was created at, plus
  bookkeeping (`last_synced_at`, `last_attempt_at`, `last_error`).
- Three top-level operations, all in `stripe_sync.py`:
  - `sync_product(local_id)` — idempotent. If no mapping exists,
    creates `Product` + `Price` and stores the mapping. If a mapping
    exists, always updates the mutable `Product` fields
    (`name`, `description`, `images`, `active`, `metadata`) and
    detects price drift; on drift, creates a new `Price`, sets it
    as `default_price`, and flips the old Price `active=false`.
    Stripe forbids editing `Price.unit_amount` and `Price.currency`
    in place — this dance is the only legal way to "edit" a price.
  - `archive_product(local_id)` — flips `Product.active=false` in
    **both** modes that have a mapping. Called from the local
    DELETE route BEFORE the mapping cascade.
  - `backfill_all()` — loop `sync_product` over every active
    local product; returns counts plus a small sample of errors.
- Mode separation: every API call goes through
  `stripe_client.get_stripe_for_mode(mode)` which uses a per-mode
  cached key without mutating the global `stripe_settings.mode`.
  This is the safe primitive for cross-mode operations like
  `archive_product` (which needs to touch both catalogs from a
  single request).
- All Stripe calls are wrapped in try/except; failures stamp
  `last_error` on the mapping and bubble a `{ok: False}` dict
  out — they NEVER raise out into the local CRUD path, so a
  Stripe outage doesn't break the admin UI.

## Data model
`stripe_product_sync (local_product_id, mode, stripe_product_id,
stripe_price_id, synced_price_cents, synced_currency,
last_synced_at, last_attempt_at, last_error)` with a UNIQUE
constraint on `(local_product_id, mode)` so the upsert in
`_upsert_mapping` is well-defined.

## API surface (Python module, not HTTP)
- `stripe_sync.sync_product(local_id) -> dict`
- `stripe_sync.archive_product(local_id) -> dict`  (per-mode result)
- `stripe_sync.backfill_all() -> {synced, failed, skipped, errors}`
- `stripe_sync.get_sync_status_rows() -> {mode, rows, count}` for
  the admin status table.

## Key files
- `stripe_sync.py` — entire engine in one file (~445 lines).
- `stripe_client.py` — `get_stripe_for_mode` is the safe primitive
  this engine relies on.
- `stripe_settings.py` — `get_mode()`, `set_autosync()`, and the
  `last_backfill_summary` snapshot stamped by `record_backfill`.

## External dependencies
- Stripe Python SDK.
- Sentry SDK (optional) — `sync_product` reports unexpected
  exceptions if Sentry is wired up.

## Pitfalls
- **Never `stripe.Price.modify(unit_amount=...)`.** It will return
  an error; Stripe's data model treats Price as immutable for
  amount/currency. The "edit a price" path is always
  create-new + set-as-default + deactivate-old.
- **Don't delete old Prices.** In-flight Checkout Sessions reference
  them by id. `active=False` is the safe retire — it disappears
  from the dashboard but Sessions in progress still work.
- **Mode mutex.** `archive_product` must touch both modes; doing
  that with `set_mode(other)` + `get_stripe()` + `set_mode(back)`
  races with concurrent requests. `get_stripe_for_mode(m)` is the
  one and only correct primitive.
- **Mapping cascade on local DELETE.** The mapping FK CASCADES on
  the local `products` row delete; you MUST call `archive_product`
  before the DELETE or you lose the Stripe ids and orphan the
  catalog entries.
- **Stripe accepts at most 8 image URLs.** The helper
  `_gallery_to_image_list` dedupes and caps at 8 — without that,
  large galleries throw at sync time.
- **Failure isolation.** Treat Stripe like an unreliable third
  party. The local CRUD path must succeed even when Stripe is down;
  the next backfill / next edit retries.

## Adaptation notes
- One-way only. If you need two-way sync (admin edits a Price in
  the Stripe dashboard and wants it reflected locally), add a
  webhook listener on `product.updated` / `price.created` — but
  beware of feedback loops (our own `Product.modify` re-triggers
  `product.updated`).
- The `(local_product_id, mode)` key generalises to any source
  table; if you mirror gallery_cards or events, the same pattern
  drops in with a renamed mapping table.
- Cache `last_synced_at` in your status table render — Stripe
  pagination is slow and an admin staring at "Sync status" doesn't
  want a round-trip per row.

## Related skills
- `01-stripe-checkout-dispatcher.md` — consumes the `Price.id`s
  this engine creates.
- `02-idempotent-stripe-webhook.md` — references `Product`s by
  their metadata, which `sync_product` stamps with
  `local_product_id` and `local_slug`.
