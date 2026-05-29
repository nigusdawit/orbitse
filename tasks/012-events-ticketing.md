# Task 012 — M12: Events ticketing

## Goal
The events subsystem (absent today): event listings + RSVPs with free/paid/
donation modes and capacity reservation.

## Acceptance criteria
- [ ] Schema: `events` (slug, title, start_at/end_at, location, capacity, price
      mode free|paid|donation, status) + `event_rsvps` (name/email/guests/notes,
      payment_status).
- [ ] Public: `GET /api/events`, `GET /api/events/<slug>`, `POST /api/events/
      <slug>/rsvp` — free saved immediately; paid/donation → pending + Stripe
      Checkout (via M11), capacity reserved at RSVP time (no double-sell).
- [ ] Webhook routing (M11) flips event RSVPs paid/expired.
- [ ] Admin: events CRUD, RSVP list, delete RSVP.
- [ ] `lookup_events` chat tool + events in the site index.

## Test requirements
- Gate: event CRUD; free RSVP saved; capacity enforced (over-capacity rejected);
  paid RSVP creates pending + (Stripe stubbed) returns redirect; lookup_events.

## Dependencies: 011   ## Status: not_started   ## Branch: task/012-events-ticketing
