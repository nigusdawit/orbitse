# Unified Media Library + WebP Variant Pipeline

## When to use
You have a Flask app where admins (and eventually the AI through `generatePage`) need to upload, browse, reuse, and serve images, videos, and audio from one consistent place — and you want every served image to automatically get a smaller WebP variant so the public site loads fast on mobile, without forcing the admin to think about it. This is the storage substrate that every other media-touching feature in the template (gallery cards, blog post bodies, presentation slides, custom sections, generated-page hero images) actually plugs into.

> Note: there is **no** in-product AI image-generation tool. The AI can reference any existing media URL it learns about through the site-index, but it cannot create new image bytes. If you want that, add a separate webhook skill (see skill 08) pointing at OpenAI Images or a similar provider — this skill documents only the persistence + serving substrate.

## Architecture
One table, one storage helper, one variant pipeline, three admin routes.

`uploaded_images` is the unified media row. Originally for images only (per the table name), later extended via additive `ALTER`s to carry videos and audio with the same schema. The minimal columns are:

- `id SERIAL PRIMARY KEY`
- `filename TEXT NOT NULL` — the random on-disk name (e.g. `b7e1d2…cae.jpg`).
- `original_name TEXT DEFAULT ''` — what the admin uploaded the file as, kept only for the admin browser.
- `file_size INTEGER DEFAULT 0` — bytes.
- `uploaded_at TIMESTAMP DEFAULT NOW()`
- `media_type` and `mime_type` (added later) — distinguish `image`/`video`/`audio` so the same list route can power image/video/audio pickers.

There is intentionally no `source`, no `created_by`, no `tags`, no `bytes` column, no provider-prompt JSON — the table is a thin index over the `uploads/` directory.

Upload flow:
1. Admin posts a multipart form to `POST /admin/api/media/upload`. The route accepts one OR many files in the same request (field `files` for multi, `file` for single). The media type is **inferred from the file extension** by `_classify_media` — there is no client-supplied `type` hint.
2. Each file is renamed to a random hex token plus its original extension and written under `uploads/<token>.<ext>` via `storage.save_*` helpers.
3. For images, `image_optimize.generate_webp_variants(filename)` runs synchronously — it produces same-name `.webp` siblings at one or more responsive widths so `<picture>` / `<img srcset>` can pick the right one. The original is kept intact for downloads.
4. An `uploaded_images` row is inserted and the route returns the resulting `{id, filename, url}` so the calling admin tab can drop it into a form.

Serving:
- Files are served by a **custom `serve_upload` route at `/uploads/<filename>`** (app.py ~line 24550), not Flask's plain static handler. The custom route gives the app two superpowers: (1) **on-demand variant generation** — if a `.webp` sibling is missing when first requested, it's generated synchronously on that request and cached for subsequent visitors; (2) **CDN origin-pull awareness** — when a CDN base URL is configured, the route 301-redirects browser hits to the CDN, and skips that redirect for origin-pull requests that carry the `X-CDN-Origin-Pull: 1` header so the CDN can actually fetch the file. URLs stored in product tables (gallery cards, blog posts, etc.) remain plain `/uploads/<filename>` strings.

Regeneration (after the variant logic changes, after the width breakpoints are tweaked, or just to backfill):
- The admin "Performance" tab fires `POST /admin/api/performance/regenerate-image-variants` (handled by `admin_regenerate_image_variants` in `app.py`, ~line 24775). It is **local-storage-only** — for S3-backed deployments the route returns HTTP 400 and the admin must script per-file regeneration via their CDN tooling. It scans every JPEG/PNG file under the `uploads/` directory (skipping anything `image_optimize.is_variant_filename` already identifies as a variant), calls `delete_variants(name)` then `generate_webp_variants(name)` on each, and returns a JSON summary `{regenerated, skipped, errors, total_scanned}` for the UI to show. Note the keys are `regenerated` / `total_scanned` — not `regenerated_count`.

## Data model
- `uploaded_images(id SERIAL PK, filename TEXT, original_name TEXT, file_size INTEGER, uploaded_at TIMESTAMP, media_type TEXT, mime_type TEXT)` — that's the whole table. Variants live on disk only, not in the DB.

## API surface
Public:
- `GET /uploads/<filename>` — handled by the custom `serve_upload` route (NOT Flask's plain static handler). Same path for originals and for `.webp` siblings; the route lazily generates a missing variant on first request and (when a CDN base URL is configured) 301-redirects browser hits to the CDN while letting origin-pull requests through.

Admin (all `@admin_required`):
- `GET /admin/api/media[?type=image|video|audio]` — list rows from `uploaded_images`, optionally filtered.
- `POST /admin/api/media/upload` — multipart upload. Accepts `files` (multi) or `file` (single). The media type is **inferred from the file extension** server-side (`_classify_media`) — there is no `type` form field. Response shape is `{"saved": [<row>, ...], "errors": [{"filename":..., "error":...}, ...]}`, not a single record.
- `DELETE /admin/api/media/<media_id>` — removes the `uploaded_images` row and best-effort deletes the original file from the storage backend. **Does NOT delete the `.webp` sibling variants** — they become orphans on disk (see Pitfalls).
- `POST /admin/api/performance/regenerate-image-variants` — re-run the variant pipeline over every JPEG/PNG in `uploads/`. Local-storage backends only; S3 returns HTTP 400.

## Key files
- `app.py` — `uploaded_images` table init (~line 1262), `media_type`/`mime_type` ALTERs further down, the four media routes (~line 24646+), and `admin_regenerate_image_variants` (~line 24775).
- `image_optimize.py` — `generate_webp_variants(filename)`, `delete_variants(filename)`, and `is_variant_filename(name)`. There is no `image_variants_supported` function; the admin Performance JSON instead surfaces a `regenerate_supported` boolean (true only when the storage backend is `"local"`), and the UI dashboard re-exposes it as `image_variants_supported` for display purposes.
- `storage.py` — file-write helpers shared by media upload, KB document storage, contract uploads, etc. Single seam to swap local disk for object storage.
- `templates/admin/dashboard.html` — Media Library tab and the Performance tab's "Regenerate image variants" button.

## External deps
- **Pillow** (with WebP support — usually present in Pillow's default build) for the `.webp` variant generation. If Pillow is missing or the build lacks WebP, the optimizer cleanly no-ops and `image_variants_supported` returns false; uploads still succeed, they just don't get variants.

## Pitfalls
- **The table is deliberately thin.** Don't add `tags`, `created_by`, or `source` columns just because they "feel useful" — the bulky metadata for individual product images (alt text, captions) belongs on the product row that references the URL, not on `uploaded_images`. Mixing the two leads to duplicate-source-of-truth bugs.
- **No DB-side dedupe.** Two admins uploading the same logo twice get two rows pointing at two on-disk copies. If you need dedupe, hash the bytes before insert and look up by hash — but adding that column needs a backfill plan.
- **WebP variants are not in the DB.** After a regenerate run, the `.webp` siblings on disk are the source of truth. A nightly orphan-file GC should match files-on-disk against `uploaded_images.filename` AND each `<filename>.webp`-style sibling so it doesn't wipe variants for live rows.
- **No SSRF for URL imports.** If you add a "paste a URL" import later, you MUST route the fetch through `_webhook_url_safe` (see skill 08) — admin-pasted URLs are not safe by default.
- **EXIF leaks.** Admin uploads (phone photos) carry GPS coordinates. The variant pipeline currently does not strip EXIF from the original. If the original is publicly servable, you are leaking metadata. Strip EXIF in the upload route before persisting if your tenants ship customer photos.
- **DELETE currently leaves variant siblings on disk.** `admin_delete_media` only removes the row from `uploaded_images` and best-effort calls `storage.delete(filename)` on the original — it does NOT enumerate and remove the corresponding `<filename>-w400.webp`, `-w800.webp`, `-w1600.webp` siblings. They become orphans that survive until the next regenerate sweep (which deletes-then-rebuilds variants only for surviving originals; orphans from already-deleted originals stay forever). If this matters, extend the delete handler to also call `image_optimize.delete_variants(filename)` before the storage delete.
- **Backwards-compat ALTER discipline.** `media_type` / `mime_type` were added later — every read site must tolerate `NULL` for legacy rows. If you add columns, add them `DEFAULT` and `NULL`-safe; never `NOT NULL` without a backfill.
- **Synchronous variant generation blocks the request.** A 10 MB photo can take a few seconds to convert. For a multi-file upload the route can hold a worker for tens of seconds. If you push this further, move variants to a background worker (or use the in-process tick scheduler skill).

## Adaptation notes
- For a true AI-image-generation feature, wire a custom webhook skill (skill 08) to OpenAI Images: the webhook returns a URL, your handler downloads the bytes, calls the existing `storage` + `image_optimize` + `uploaded_images` INSERT path, and returns the new `/uploads/...` URL. Result: zero changes to product tables, full reuse of the variant pipeline, and the AI's images show up in the same admin Media Library as uploads.
- For per-tenant scoping, add `tenant_id` to `uploaded_images` and to the on-disk path (`uploads/<tenant>/<filename>`) so storage migrations stay clean.
- For video posters, store the still as a sibling `<filename>.poster.jpg` and reference it by convention — same "no extra DB column" principle as `.webp` siblings.
- For an `object_storage` backend, only `storage.py` and the `/uploads/<filename>` route change; product tables keep storing `/uploads/<filename>` strings and a route rewrite resolves them.

## Adoption checklist
- [ ] Create `uploaded_images` with the minimal column set.
- [ ] Add `storage.save_image(bytes, ext)` (and equivalent for video/audio) as the single write path; swappable backend.
- [ ] Add `image_optimize.generate_webp_variants(filename)` with a capability flag for environments missing libwebp.
- [ ] Wire the four admin routes (`GET /admin/api/media`, `POST /admin/api/media/upload`, `DELETE /admin/api/media/<id>`, `POST /admin/api/performance/regenerate-image-variants`).
- [ ] Decide whether `DELETE` should also remove `<filename>.*` sibling variants — current code does not; add `delete_variants(filename)` to the handler if you want clean removal.
- [ ] Strip EXIF before persisting admin uploads if you serve originals publicly.
- [ ] If/when you add AI generation, do it via a webhook skill that lands its bytes through this same upload pipeline — do not create a parallel table.
