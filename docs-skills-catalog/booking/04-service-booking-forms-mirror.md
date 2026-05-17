# Service Bookings ↔ Forms Mirror (Managed Form, Reject-On-Mutate)

**Category:** Booking · Analytics integration
**Status:** Production

## When to use
You have two surfaces that both want to be the "list of leads /
contacts who interacted with you":

- The **Bookings** tab — full booking detail, payment status,
  add-ons, contract files.
- The **Forms** tab — every form submission across the site, with
  marketing attribution (UTM, referrer, device, browser, partial-
  abandon recovery, etc.).

A naive integration duplicates the data and the two views drift.
The right pattern is to make the booking flow *be* a form
submission as far as the Forms tab is concerned — a managed
"shadow form" per service, auto-created the first time the
service is booked, write-protected against admin edits so it can
never desync from its parent service.

## Architecture
- One managed `custom_forms` row per service:
  `form_type='service_booking', linked_service_id=<service.id>,
  slug='service-booking-<svc-slug>'`. Created lazily by
  `_ensure_service_booking_form(service)` (~app.py:30414) on the
  first booking attempt.
- The Forms list renders this row with a coloured "Service
  Booking" badge so admins know it's auto-managed.
- All mutation endpoints — Edit, Delete, add field, remove field —
  call `_reject_if_managed(form_id)` (~app.py:26708) which returns
  409 if the form is managed. The form can only be changed by
  editing the parent service.
- Two write paths feed `form_submissions`:
  - **Partial save** — `POST /api/services/<slug>/booking-partial`
    (~app.py:30507). Debounced 800 ms on the client once an email
    is typed. Saves with status like `partial` so the Forms tab's
    "abandoned leads" view surfaces them.
  - **Final booking** — `api_book_service` (~app.py:30715) updates
    the same `form_submissions` row (matched by `session_id`)
    to status `new` and writes the full submission payload.
- The matching key is a per-tab `session_id` (cookie or
  sessionStorage UUID) so the abandoned-cart row is promoted to a
  full submission when the same visitor finishes — no duplicate.
- Tracking metadata captured in both partial and final writes:
  `session_id, page_url, referrer_url, language, screen_resolution,
  ip_address, user_agent, browser, os`, plus
  `utm_source, utm_medium, utm_campaign, utm_term, utm_content`.

## Data model
- `custom_forms (id, slug, form_type, linked_service_id, name,
  ...)` — the `form_type='service_booking'` and
  `linked_service_id` pair is what marks a row as managed. Form
  fields live in a separate `form_fields` table joined by
  `form_id`.
- `form_submissions (id, form_id, session_id, status,
  submission_data, utm_*, page_url, referrer_url, language,
  screen_resolution, ip_address, user_agent, browser, os, ...)`
  (~app.py:1303–1324) — the payload column is `submission_data`
  (JSONB); `session_id` is the dedupe key for partial-to-final
  promotion.

## API surface
- `POST /api/services/<slug>/booking-partial` — debounced 800 ms
  client-side once an email is present.
- `POST /api/services/<slug>/book` — final booking; also writes /
  promotes the form submission.
- Forms-tab CRUD on managed rows returns 409 via
  `_reject_if_managed` — endpoints: form edit, field
  add/edit/delete, form delete. The Submissions view continues to
  work normally.

## Key files
- `app.py` — `_ensure_service_booking_form` (~30414),
  `_reject_if_managed` (~26708), partial endpoint (~30507),
  final-booking promotion (~30715), `form_submissions` schema
  (~1303).

## External dependencies
- None — pure DB + Flask.

## Pitfalls
- **Lazy-create, don't migrate.** Creating the managed form for
  every existing service in a migration creates thousands of empty
  forms; lazy-create on first booking attempt keeps the Forms
  list lean.
- **Match by `session_id`, not by email.** A visitor may type two
  different emails into the partial-save before finishing; you
  want the same row to keep getting updated, then promoted. The
  email is data, the session is identity.
- **Reject mutations server-side, not just in the UI.** The
  managed-form badge is a hint; `_reject_if_managed` is the
  enforcement. Any code path that mutates form fields must call
  it (form edit, field add/edit/delete, form delete).
- **Don't reject submissions** — only structural mutations. The
  Submissions view (read + status flip) must keep working or
  admins can't triage leads.
- **Field schema is derived from the service.** If you let the
  managed form drift from the service's field set, the Forms tab's
  table view goes out of sync. Re-derive on every read of the
  managed form (or re-write fields_json each time
  `_ensure_service_booking_form` runs).
- **Partial saves need email-before-write gating.** Without it,
  you create a `form_submissions` row on every keystroke and the
  Forms tab fills with empty rows. The 800 ms debounce + "only
  once an email is present" rule keeps the noise out.

## Adaptation notes
- The same managed-form pattern fits any auto-generated lead
  source: event RSVPs, contact-us submissions, newsletter signups.
  The key invariants are (a) one row per source, (b) write-
  protected against admin mutation, (c) labelled in the UI so it's
  not surprising.
- If you ship multi-tenant, scope the managed-form lookup by
  `tenant_id` AND `linked_service_id` — slug collisions across
  tenants are otherwise inevitable.
- For partial-save analytics, the `status` enum is the right place
  to encode the abandon stage (`partial`, `email_captured`,
  `new`, `qualified`, …) rather than a separate column.

## Related skills
- `01-weekly-availability-engine.md` — the booking write writes
  here too.
- `02-service-addon-snapshot.md` — the add-on snapshot is included
  in the form submission's `submission_data` JSONB payload.
- `../payments/01-stripe-checkout-dispatcher.md` — the dispatcher's
  three-action envelope.
- The Forms infrastructure skills (Batch 6) describe the abandon-
  capture, UTM, and submission-status enums in depth.
