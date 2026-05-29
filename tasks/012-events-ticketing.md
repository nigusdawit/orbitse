# Task 012 — M12: Events ticketing

## Goal
The events subsystem (absent today): event listings + RSVPs with free/paid/
donation modes and capacity reservation.

## Acceptance criteria
- [x] Schema: `events` (slug, title, start_at/end_at, location, capacity, price
      mode free|paid|donation, status) + `event_rsvps` (name/email/guests/notes,
      payment_status).
- [x] Public: `GET /api/events`, `GET /api/events/<slug>`, `POST /api/events/
      <slug>/rsvp` — free saved immediately; paid/donation → pending + Stripe
      Checkout (via M11), capacity reserved at RSVP time (no double-sell).
- [x] Webhook routing (M11) flips event RSVPs paid/expired (expiry frees seats).
- [x] Admin: events CRUD, RSVP list, delete RSVP.
- [x] `lookup_events` chat tool + events in the site index.

## Test requirements
- Gate: event CRUD; free RSVP saved; capacity enforced (over-capacity rejected);
  paid RSVP creates pending + (Stripe stubbed) returns redirect; lookup_events.

## Dependencies: 011   ## Status: done   ## Branch: task/012-events-ticketing

## Notes
Gate: 224/224 green incl. free RSVP confirm + seat reservation, over-capacity
409, last-seat allowed, paid RSVP pending+redirect with per-guest amount,
webhook confirm + expiry-frees-seats, lookup_events seats_remaining. Unit:
`test_events.py` pins the seats math (capped / unlimited→None / clamp-to-zero).
Drift: M12 work was committed directly to main (commit e4e24ad) — I forgot to
cut the task branch first; a `task/012-events-ticketing` pointer was created
retroactively at that commit. No PR flow (local-only repo).
