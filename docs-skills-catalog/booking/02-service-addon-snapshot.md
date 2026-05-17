# Service Add-On Snapshot (Price-Frozen at Booking Time)

**Category:** Booking · Pricing
**Status:** Production

## When to use
You sell services with optional priced extras (gift wrap, extra
guest, equipment rental, premium support). Two requirements collide:

- The admin must be able to edit the add-on catalog freely — change
  prices, rename, deactivate, delete.
- A booking placed last Tuesday must still show the same line items
  and the same total *forever*, even if the admin deleted that
  add-on this morning.

The fix: at the moment of booking, write a JSON snapshot of every
selected add-on onto the booking row. The live `service_addons`
table is the source of truth for *future* bookings; the snapshot is
the source of truth for *this* booking.

## Architecture
- Catalog table `service_addons` (`id, service_id, name, description,
  price_cents, sort_order, is_active`) — admin-edited.
- Booking row carries two columns:
  - `selected_addon_ids INTEGER[]` — what the visitor ticked. Useful
    for analytics ("which add-ons are most popular?").
  - `addon_snapshot JSONB` — the frozen-at-booking-time list of
    `{id, name, price_cents}` for every selected, currently-active
    add-on at the moment of the POST.
- Booking endpoint (`api_book_service` ~ app.py:30602–30620):
  1. Read the submitted add-on ids.
  2. SELECT the matching `is_active = true` rows from
     `service_addons` for this service.
  3. Build the JSON snapshot in the same response.
  4. INSERT that snapshot into `service_bookings.addon_snapshot`
     alongside the rest of the booking row (~ app.py:30676).
- All downstream consumers (Stripe `line_items` calculation,
  confirmation email, admin booking detail view, invoice PDF) read
  `addon_snapshot` — never the live catalog.

## Data model
- `service_addons (id, service_id, name, description, price_cents,
  sort_order, is_active)`.
- `service_bookings.selected_addon_ids INTEGER[]`.
- `service_bookings.addon_snapshot JSONB` — list of objects
  `[{id, name, price_cents}, ...]`.

## API surface (data shape)
- `POST /api/services/<slug>/book` body: `addon_ids: [int, ...]`
  alongside the rest of the booking payload.
- The booking response echoes the snapshot so the success page can
  render the line items without a second round-trip.

## Key files
- `app.py` — `api_book_service` (~30586+), catalog schema in
  `init_db()` (~3435), booking schema with both snapshot columns.

## External dependencies
- None.

## Pitfalls
- **Read the catalog inside the same transaction as the INSERT.**
  Reading first, then INSERTing after an `await` (or a long
  validation step) opens a window where the admin disables an
  add-on between the two — you'd snapshot an item the visitor
  shouldn't have been able to book.
- **Filter `is_active = true` at snapshot time.** A visitor could
  POST an id for a deactivated add-on (re-submitting a stale form,
  manipulating the request). Silently dropping it is the right
  behaviour; failing the whole booking is annoying.
- **Don't store the *current* `service_addons.price_cents` on the
  snapshot.** Stamp the price at the moment of the snapshot read
  — that's the whole point. The catalog row may change tomorrow.
- **Snapshot is for billing, ids are for analytics.** Don't drop
  `selected_addon_ids` — without them you can't answer "how often
  do people book add-on X" across booking history.
- **Sum the line items on the server, not the client.** The booking
  total stamped on the row is `service.price_cents + sum(snapshot
  price_cents)`; never trust a client-computed total in the
  request body.

## Adaptation notes
- This is the same "stamp the unit price at write time" pattern as
  the unit-price ledger (`../payments/05-unit-price-ledger.md`),
  applied to product-shaped data instead of usage-metric-shaped
  data. JSONB is the right shape because you want N items per
  booking and you never query by add-on price.
- For variant pricing (e.g. tiered add-ons with size/colour),
  expand each option to its own catalog row instead of storing the
  variant inside the JSON — keeps the snapshot shape stable.
- If you ever need to refund a single add-on, stamp a
  `refunded_at` field on the JSON object rather than mutating
  `price_cents` to 0 — preserves the original total for audit.

## Related skills
- `01-weekly-availability-engine.md` — capacity per *slot*, this
  skill governs *price* per slot.
- `04-service-booking-forms-mirror.md` — the form-submission row
  that mirrors a booking also captures the chosen add-ons so the
  Forms tab analytics doesn't undercount revenue.
- `../payments/01-stripe-checkout-dispatcher.md` — builds Stripe
  `line_items` from the snapshot.
- `../payments/05-unit-price-ledger.md` — same "freeze the price at
  write time" principle.
