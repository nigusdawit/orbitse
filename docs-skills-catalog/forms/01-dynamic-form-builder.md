# Dynamic Form Builder (Admin-Authored Forms with Multi-Step + Drag-Reorder)

**Category:** Forms
**Related:** `forms/02-partial-abandon-capture.md`, `forms/03-managed-system-forms.md`, `forms/04-utm-device-metadata.md`

## When to use
You want the site operator to design and deploy new lead-capture forms (contact, RSVP, quote request, custom intake) from an admin UI without code changes — including field types, validation, required-ness, multi-step grouping, and visual reordering — and have submissions flow into a single unified `form_submissions` table that downstream tooling (analytics, automations, exports) can consume.

## Architecture
- **Two tables in a parent/child relationship:** `custom_forms` (one row per form) holds metadata (name, slug, success message, status), `form_fields` (many rows per form) holds the field definitions.
- **Field type is a string column**, not a separate table — values like `text`, `email`, `tel`, `textarea`, `select`, `radio`, `checkbox`, `date`, `number`. The frontend renderer (`public/script.js`) switches on this string to pick the HTML control.
- **Options for `select`/`radio`/`checkbox`** live in a JSONB `options` column (array of `{value, label}` objects). Keeping it in one column avoids a third table at the cost of not being able to query "all forms that have a 'Premium' option".
- **Multi-step grouping** is a simple integer `step` column on each field — 0 = single page form, 1+ = multi-step with step numbers as visual page breaks. No separate `form_steps` table — the highest `step` value defines how many steps exist.
- **Drag-reorder** mutates `sort_order` (integer, gap-filled) per field. A dedicated reorder endpoint accepts an array of field ids and rewrites `sort_order` for the whole form atomically.
- **Slugs are the public handle.** The public site renders `/forms/<slug>` (or embeds the form via JS), and submits to `/api/forms/<slug>/submit`. The slug is the contract between admin and public site, not the integer id.

## Data model
Table `custom_forms` (`app.py:~1271`):

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `name` | Admin label |
| `slug` UNIQUE | Public URL handle |
| `description` | Optional preamble shown above the fields |
| `status` | `active` \| `inactive` (hides from public) |
| `submit_button_text` | Defaults to "Submit" |
| `success_message` | Shown after submit |
| `sort_order` | For the admin list ordering |
| `form_type` | `'standard'` (admin-authored, fully editable) or a managed type like `'service_booking'` — see skill #3 |
| `linked_service_id` FK NULL | Only set for managed forms |
| `created_at`, `updated_at` | |

Table `form_fields` (`app.py:~1285`):

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `form_id` FK | ON DELETE CASCADE |
| `field_type` | `text`, `email`, `tel`, `textarea`, `select`, `radio`, `checkbox`, `date`, `number`, ... |
| `label` | Shown above the input |
| `name` | Machine name, becomes the JSON key in submissions |
| `placeholder`, `default_value`, `help_text` | |
| `required` BOOLEAN | |
| `options` JSONB | For `select`/`radio`/`checkbox` |
| `validation_regex` | Optional client + server validation |
| `width` | `'full'` \| `'half'` (visual layout hint) |
| `sort_order` | Drag-reorder position within the form |
| `step` | Step number, default `1`; same value for every field on a single-page form, increments for multi-step |

## API surface
- `GET    /admin/api/forms` — list (`app.py:~26639`)
- `POST   /admin/api/forms` — create (`app.py:~26652`)
- `PUT    /admin/api/forms/<id>` — update form metadata (`app.py:~26726`)
- `DELETE /admin/api/forms/<id>` — cascade delete fields + submissions (`app.py:~26753`)
- `POST   /admin/api/forms/<id>/fields` — add field
- `PUT    /admin/api/forms/<id>/fields/<field_id>` — update field
- `DELETE /admin/api/forms/<id>/fields/<field_id>` — remove field
- `PUT    /admin/api/forms/<id>/fields/reorder` — drag-reorder (`app.py:~26858`)

Public submit + render endpoints are covered in skill #4.

## Key files
- `app.py:~1271` — `custom_forms` DDL
- `app.py:~1285` — `form_fields` DDL
- `app.py:~26639..26900` — admin CRUD
- `templates/admin/dashboard.html` — form builder UI (search "Forms" tab)
- `public/script.js` — dynamic renderer (switch on `field_type`)

## External dependencies
- A frontend drag library (or HTML5 native drag events) for reorder UX — verify which the dashboard uses.

## Pitfalls
- **Slug collisions on rename.** If admin renames "Contact" → slug `contact`, but slug `contact` is already taken by a managed form, the create fails. Surface a friendly error and suggest a unique slug.
- **Removing a field drops historical data**, because submissions are stored as a JSONB blob keyed by field `name`. Old submissions still have the old key — design the admin's "submissions" view to render unknown keys gracefully rather than 500ing.
- **Renaming a field's `name` column** has the same problem in reverse — old submissions still reference the old name. Either lock `name` once a submission exists, or accept the historical drift and document it.
- **Multi-step is a hint, not a hard boundary.** The server validates required-ness across the WHOLE form on submit, not per-step. If you partial-save (skill #2), validate only the fields the visitor has reached so far.
- **JSONB `options` is unindexed.** Don't try to query "which forms offer Tier X" — denormalize if you need that.
- **CSRF / spam:** admin CRUD is `@admin_required`; public submit needs its own protection (rate limit + optional hCaptcha) since the form is publicly addressable by slug.

## Adaptation notes
- For conditional fields (show field B only if field A == "Yes"), add a `visible_when` JSONB column with `{field_name, op, value}` and have the renderer hide/show on input change. Keep the server validation as-is so a malicious POST that bypasses visibility logic still gets validated against the schema.
- For file uploads, add `field_type='file'` and a separate `form_submission_files` table (don't store binary in the JSONB blob).
- To export submissions to a CRM (HubSpot, Salesforce), add an `automations` row that watches the table and pushes new rows via webhook — keep the form table itself ignorant of integrations.
- The same renderer logic powers the AI chatbot's "form collection" feature — when the AI decides the visitor needs a form, it pushes the same `slug`-keyed structure into the chat UI and the same JS renders it inline.
