# Per-section SEO overrides

## When to use
A single-page (snap-scroll) site that exposes deep links like `/services` or `/about` that should each render with their own `<title>`, meta description, and OG image — even though the underlying HTML shell is the same homepage.

## Architecture
Each row in `page_sections` carries optional SEO override columns. When a deep-link route resolves to a specific section, the shell renderer swaps the homepage defaults for the section's overrides before sending the HTML.

Flow:
1. Operator edits `seo_title` / `seo_description` / `seo_image` on a section in the admin Page Layout tab.
2. Visitor hits `/<section-slug>` — the route handler looks up the row by slug.
3. The shell renderer (`_render_app_shell_response`) substitutes the `<title>`, meta tags, and OG/Twitter image with the section overrides (falling back to `site_settings` values when an override is blank).
4. The same overrides are also passed into the AI context block so the chatbot answers questions about that section consistently.

## Data model
Added columns on `page_sections`:
- `seo_title TEXT NULL`
- `seo_description TEXT NULL`
- `seo_image TEXT NULL` (URL into `/uploads/...`)

All nullable — a NULL means "inherit homepage default".

## API surface
- Admin reads/writes flow through the existing page-sections CRUD (`/admin/api/page-sections/...`).
- Public routes: `GET /<slug>` (section deep link), which inherits the per-section overrides via the shared shell renderer.

## Key files
- `app.py:2360-2362` — `ALTER TABLE page_sections ADD COLUMN seo_*` migration.
- `app.py:7042-7053` — `serve_section()` looks up overrides and calls `_render_app_shell_response` with them.
- `app.py:15002` — AI prompt builder threads section overrides into the live-site context.

## External deps
None.

## Pitfalls
- HTML-escape every override field before substituting into `<title>` / `<meta>` — admins paste quotes, ampersands, and emoji.
- Truncate `seo_description` server-side to ~160 chars to match Google's display limit; the admin UI should mirror the cap.
- OG images need absolute URLs — combine with `site_settings.seo_canonical_url` rather than emitting a relative `/uploads/...` path that some crawlers won't resolve.
- Remember to invalidate any per-section cache after an override edit, or admins will refresh and see stale tags.

## Adaptation notes
- Add `seo_keywords` or `seo_robots` (noindex toggle) the same way — nullable columns, fall-back-on-NULL renderer logic.
- The same pattern works for any "child resource overrides parent metadata" — blog categories, product collections, event series.

## Adoption checklist
- [ ] Add nullable `seo_*` columns to the section table.
- [ ] Extend admin form with three optional inputs and live preview.
- [ ] Have the shell renderer accept an `overrides` dict and fall back per-key to defaults.
- [ ] HTML-escape every value at render time.
- [ ] Build absolute OG image URLs from `seo_canonical_url` + the stored path.
