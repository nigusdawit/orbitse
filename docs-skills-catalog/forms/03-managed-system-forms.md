# Managed System Forms (Auto-Generated, Mutation-Locked)

**Category:** Forms
**Related:** `forms/01-dynamic-form-builder.md`, `booking/04-service-booking-forms-mirror.md`

## When to use
Other features in the app (service bookings, event RSVPs, contact captures from the chatbot, etc.) want their submissions to appear in the same admin Forms tab and reuse the same submissions UI, analytics, automations — without the admin being able to accidentally rename fields, delete the form, or otherwise break the link between the feature and the form.

## Architecture
- **Single submissions surface.** Everything that captures a lead writes to `form_submissions`, regardless of whether the form was hand-built or auto-generated. Operators have one place to look.
- **Discriminator column on `custom_forms`:** `form_type` is `'standard'` for admin-authored forms and a string like `'service_booking'` for managed ones. `linked_service_id` (or analogous FK) points back to the feature row that owns it.
- **Lazy creation.** The first time a feature needs its form (e.g. first booking attempt for a service), an `_ensure_xxx_form()` helper runs `INSERT ... ON CONFLICT DO NOTHING` to create the `custom_forms` row + its fixed field set. No admin step required.
- **Mutation lock.** Every admin CRUD endpoint that could change a managed form (rename, delete, add/remove/reorder fields) calls a `_reject_if_managed(form)` guard at the top and returns HTTP 403 if `form_type != 'standard'`. The Submissions view stays fully usable — only the **structure** is locked.
- **Visual badge in admin.** The Forms list renders a colored badge ("Service Booking", "Contact", etc.) next to managed forms so the operator immediately understands why the Edit/Delete buttons are missing.
- **Deletion of the parent cascades** to the form. When the operator deletes the underlying service, the managed form row is deleted too (Postgres `ON DELETE CASCADE` from the FK).

## Data model
On `custom_forms` (see skill #1):
- `form_type TEXT NOT NULL DEFAULT 'standard'`
- `linked_service_id INTEGER NULL REFERENCES services(id) ON DELETE CASCADE`

For other managed kinds, add additional FK columns (`linked_event_id`, etc.) — they're cheap, NULLable, and self-documenting.

`form_fields` rows owned by a managed form are normal rows — the lock is enforced at the application layer, not via DB triggers.

## API surface
No new public surface — managed forms are invisible to public callers except through their owning feature's endpoints (e.g. `/api/services/<slug>/book`).

Internal helpers (Python, in `app.py`):
- `_ensure_service_booking_form(service_id) -> form_id` (`app.py:~30414`) — idempotent UPSERT
- `_reject_if_managed(form) -> Response | None` (`app.py:~26697`) — guard called by every mutating admin endpoint

Admin endpoints affected:
- `PUT /admin/api/forms/<id>` — rejects if managed
- `DELETE /admin/api/forms/<id>` — rejects if managed
- `POST/PUT/DELETE /admin/api/forms/<id>/fields[...]` — all reject if managed
- `PUT /admin/api/forms/<id>/fields/reorder` — rejects if managed

## Key files
- `app.py:~1271` — `custom_forms` DDL with `form_type` + `linked_service_id` columns
- `app.py:~26697` — the `_reject_if_managed` guard (called from every mutating admin form endpoint)
- `app.py:~30414` — `_ensure_service_booking_form`
- `app.py:~30507` — booking partial-save call site (the moment that triggers ensure)
- `templates/admin/dashboard.html` — the managed-form badge styling

## External dependencies
None.

## Pitfalls
- **`_ensure` must be idempotent under concurrency.** Two booking attempts arriving simultaneously must not create two forms. Use `INSERT ... ON CONFLICT (slug) DO NOTHING RETURNING id` and re-`SELECT` if RETURNING is NULL.
- **Don't auto-delete the form when the last submission is deleted** — operators may want to retain the form for analytics even after pruning data.
- **Slug collisions.** A managed slug like `service-booking-<svc-slug>` collides if the service's slug collides. Either prefix-namespace the managed slug or include the integer id (`service-booking-<id>-<slug>`).
- **Schema drift.** If you change the field set of a managed form (e.g. add a new `guest_count` field), existing tenant forms won't auto-migrate. Add a `_repair_xxx_form()` helper that diffs expected vs actual fields and ADDs missing ones — be conservative about removing fields (existing submissions reference their names).
- **Operators will complain "I can't edit this!"** Pre-empt with inline help text on the badge ("Auto-managed by the Services feature — edit the service to change these fields").

## Adaptation notes
- Same pattern works for any auto-form. Examples already in this codebase: contact form (slug `contact-us`, type `'standard'` but conventionally treated as system), service-booking forms. Extensible to: event-RSVP forms, newsletter signups, abandoned-cart capture.
- For multi-tenant SaaS, scope `linked_*` FKs and the `_ensure` helpers by `tenant_id` — every tenant gets their own managed form per service.
- If managed forms outgrow the lock (operators legitimately want to add a custom field), introduce a `customizable_fields` whitelist column on `custom_forms` and have `_reject_if_managed` allow mutation of those specific fields only.
- To preview a managed form's structure without an admin edit UI, render the field set as read-only HTML in the Forms tab so operators understand what visitors see.
