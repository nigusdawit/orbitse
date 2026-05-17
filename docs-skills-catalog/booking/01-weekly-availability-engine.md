# Weekly Availability Engine (Rules + Per-Date Overrides)

**Category:** Booking · Scheduling
**Status:** Production

## When to use
You need to expose "what time slots are bookable for this service on
these dates?" without storing one row per slot per day. The answer
has three independent dimensions that all have to combine cleanly:

- Recurring weekly windows ("Mondays 9–12 and 14–17, 30-min slots").
- One-off changes ("blocked for the holiday on the 24th", "extra
  pop-up window on Saturday the 28th").
- What's already been taken ("slot 14:00 is full because two pending
  bookings already grabbed the two-seat capacity").

The engine resolves all three on-the-fly per request — there is no
materialised calendar table to keep in sync.

## Architecture
- Two tables describe intent, one table describes consumption:
  - `service_availability_rules` — recurring weekly windows
    (`service_id, day_of_week 0–6, start_time, end_time,
    slot_minutes, is_active`).
  - `service_availability_overrides` — per-date exceptions
    (`service_id, override_date, override_kind in {block, open},
    start_time?, end_time?, slot_minutes?`).
  - `service_bookings` — actual bookings (consumption).
- Single resolver function `_compute_availability(service, start,
  end)` (`app.py` ~ lines 29799–29898) walks each date in the
  requested range and, for each date:
  1. Generate candidate slots from the matching `day_of_week` rule
     PLUS any `open` overrides on that date.
  2. Subtract any `block` overrides — whole-day if `start_time`/
     `end_time` are NULL, otherwise timed.
  3. Subtract slots already booked: count rows in
     `service_bookings` with `status IN ('pending', 'confirmed')`
     and `payment_status NOT IN ('expired', 'refunded')` up to the
     service's `capacity_per_slot`.
- Capacity is per-slot, not per-day. A slot with two seats and one
  pending booking still shows up as "1 left".
- Pending rows count as consumed — this is what makes capacity
  reservation pre-checkout work (see
  `06-capacity-reservation-pre-checkout.md`).

## Data model
- `service_availability_rules` (~ app.py:3448): `id, service_id,
  day_of_week, start_time, end_time, slot_minutes, is_active`.
- `service_availability_overrides` (~ app.py:3462): `id, service_id,
  override_date, override_kind, start_time, end_time, slot_minutes`.
- `services.capacity_per_slot INTEGER` — used by the resolver as
  the per-slot cap.
- `service_bookings.status TEXT`, `payment_status TEXT`,
  `scheduled_date DATE`, `scheduled_start TIME`, `scheduled_end TIME`
  — the consumption signal. (The booking row stores date + start +
  end as separate columns, not a single TIMESTAMPTZ. Combine with
  the service's timezone if you need a tz-aware instant.)

## API surface
- `GET /api/services/<slug>/availability?start=YYYY-MM-DD&end=YYYY-MM-DD`
  (`app.py` ~ line 30333) — returns the resolved slot list with
  remaining capacity per slot.
- Admin CRUD on rules and overrides lives under
  `/admin/api/services/<id>/availability/...` (per-row endpoints).

## Key files
- `app.py` — `_compute_availability` (~29799), the public route
  (~30333), and the schema in `init_db()` (~3448–3471).

## External dependencies
- None beyond Postgres + the booking row writer.

## Pitfalls
- **Don't materialise slots.** A "one row per slot per day" table
  drifts the instant an admin edits a rule and you forget to
  regenerate. On-the-fly resolution is O(days × rules) — cheap.
- **Pending rows MUST count as consumed.** Otherwise two visitors
  in Stripe Checkout for the same slot both succeed. See the
  capacity-reservation skill.
- **`overrides` overlay rules, not replace them.** A `block`
  override on Monday doesn't disable Tuesday's rule. An `open`
  override adds a window; it doesn't override the rule for that day.
- **DST is per-date math.** If you store rules in local time, walk
  the date in the *service's* time zone, not UTC. This branch
  stores `scheduled_date`/`scheduled_start`/`scheduled_end` as
  date + naive times — cross-tz interpretation lives in the
  application layer. If you adapt this to a multi-tz product,
  TIMESTAMPTZ is the cleaner choice.
- **`status` vs `payment_status` filter.** Expired/refunded rows
  must NOT count as taken — that's what releases capacity after
  Stripe times out a Checkout Session.
- **Sort the merged slot list before returning.** Rules + opens may
  produce overlapping or out-of-order ranges; collapse + sort
  before computing consumption so duplicate slot-starts don't
  inflate "taken" counts.

## Adaptation notes
- The exact column names are domain-specific
  (`override_kind in {block, open}` is opinionated). What you
  actually want to copy is the **three-layer composition**: base
  rules + signed overrides + consumption.
- For multi-resource scheduling (e.g. "two stylists, three chairs"),
  the same engine works with capacity replaced by a join against a
  resources table; the slot just becomes `(date, time, resource_id)`.
- If you need to publish a calendar feed (iCal/Google Calendar),
  generate from the same resolver instead of duplicating the rules
  into a second source of truth.

## Related skills
- `02-service-addon-snapshot.md` — what gets attached to the
  booking row the engine subtracts capacity from.
- `06-capacity-reservation-pre-checkout.md` — the reason pending
  rows count as consumed.
- `../payments/01-stripe-checkout-dispatcher.md` — the Checkout
  flow that creates those pending rows.
