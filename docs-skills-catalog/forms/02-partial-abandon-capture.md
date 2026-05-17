# Partial / Abandon Form Capture

**Category:** Forms
**Related:** `forms/01-dynamic-form-builder.md`, `forms/04-utm-device-metadata.md`

## When to use
Visitors abandon forms — half-filled cart, partial quote request, scrolled past step 2 of a multi-step booking. You want to capture what they DID fill in so the operator can follow up by email/phone, and you want that capture to promote cleanly to a real submission if the visitor comes back and finishes.

## Architecture
- **Same table, different status.** `form_submissions` rows have a `status` column: `partial` while the visitor is still typing, `new` once they hit submit. There is no separate "abandoned" table — partial and final are the same row, mutated in place.
- **Session-keyed dedupe.** The frontend generates a per-tab `session_id` (UUID, persisted in `sessionStorage`) and includes it on every partial save and on the final submit. The server INSERT-or-UPDATEs on `(form_slug, session_id)`, so the same visitor accumulates writes into a single row instead of leaving a trail of duplicates.
- **Debounced auto-save.** Frontend debounces input events (~800ms) and only starts firing partial-saves once the visitor has typed a contact field (email or phone) — no point saving "first_name=J" before there's any way to reach them.
- **Promotion on submit.** The final POST to `/api/forms/<slug>/submit` looks up the existing partial row by `session_id` and UPDATEs it to `status='new'`, instead of inserting a fresh row. Net effect: zero duplicate rows even if the visitor's flow includes 12 keystrokes and one submit.
- **No cleanup job required.** Partial rows are real lead data — the operator can email them too. If your tenant policy is to expire stale partials, add a nightly sweep that deletes `status='partial' AND updated_at < now() - interval '30 days'`.

## Data model
No new table. The `form_submissions` table (see skill #4 for the full column list) gains semantic meaning via `status`:
- `partial` — created/updated by `/partial` endpoint, `submission_data` JSONB grows as the visitor types
- `new` — promoted by `/submit` endpoint, ready for the operator to action
- `viewed` / `responded` / `archived` — admin-driven downstream states

`session_id` is a NOT NULL string (UUID) used as the dedupe key.

## API surface
- `POST /api/forms/<slug>/partial` (`app.py:~27018`) — body: `{session_id, submission_data: {...}, utm/device/referrer metadata}`. Behavior: `INSERT ... ON CONFLICT (form_id, session_id) DO UPDATE SET submission_data = EXCLUDED.submission_data, updated_at = now()`. Always returns 200 with `{ok: true}` — never error to the visitor since this is a background save.
- `POST /api/forms/<slug>/submit` (`app.py:~27115`) — same shape plus full required-field validation. Promotes the matching partial row to `status='new'`, or inserts fresh if no session row exists.

## Key files
- `app.py:~27018` — `/partial` handler
- `app.py:~27042` — session_id dedupe / UPSERT logic
- `app.py:~27115` — `/submit` handler with partial-row promotion
- `public/script.js` — debounced auto-save wiring (search `partial`)

## External dependencies
None.

## Pitfalls
- **Partial rows count in analytics.** If your dashboard counts `SELECT COUNT(*) FROM form_submissions`, you'll over-report submissions 5–10x. Always filter `WHERE status != 'partial'` for "real" submissions.
- **Privacy / PII.** Partial rows can contain email/phone the visitor typed but never consented to send. Make sure your privacy policy covers this (most GDPR interpretations require it), and offer a self-serve delete path.
- **Race between debounced save and submit.** Browser fires submit while the last partial-save is still in flight → the submit can insert a brand-new row, then the partial save UPSERTs into that same row and rolls `status` back to `partial`. Fix: have the `/partial` handler include `... AND status = 'partial'` in its UPDATE WHERE clause so it can never downgrade a promoted submission.
- **Cross-tab churn.** A visitor with three tabs open will have three `session_id`s and three partial rows — by design (each tab is a separate intent). Don't try to merge them by IP/email; operators find duplicates more confusing than missing data.
- **Bot / scraper partials.** A scraper that triggers debounced saves will create one partial row per crawl. Add a simple bot heuristic (no `submission_data` after 5 saves, or UA contains `bot/`) and silently no-op.

## Adaptation notes
- For multi-step forms, track `current_step` in the partial row so the operator's dashboard can sort by "furthest progressed" — strong recovery signal.
- For shopping carts (not strictly forms), the same pattern works: `cart_carts` table keyed by `session_id`, `status='active' → 'checked_out' → 'abandoned'` driven by a TTL sweep.
- To send a "you forgot to finish" follow-up email, add an automation that watches for `partial → no submit within 1h AND email field non-empty` and queues a campaign send via the messaging skill.
- The same `session_id` is the join key used by the analytics module (skill #4) — keep it stable across the visitor's whole journey, don't regenerate per form.
