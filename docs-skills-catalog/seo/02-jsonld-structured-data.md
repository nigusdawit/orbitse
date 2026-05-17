# JSON-LD structured data injector

## When to use
You want rich-result eligibility in Google (sitelinks search box, knowledge-panel logo, article cards) without authoring a separate metadata system. JSON-LD lets you ship structured data inline and update it from the same DB that drives the page.

## Architecture
Server-side templating injects a `<script type="application/ld+json">` block at a known placeholder in the HTML shell:

- `public/index.html` contains the comment marker `<!-- JSON_LD_INJECT -->`.
- On every homepage request the shell renderer builds a JSON-LD payload from `site_settings` and `business_info` (Organization + WebSite schema) and substitutes the marker with the rendered `<script>` tag.
- Per-page templates (e.g. `templates/blog_post.html`) emit their own `BlogPosting` block at render time using the post row.

This keeps homepage structured data centralised while still letting content-specific pages emit their own schema without round-tripping through the homepage shell.

## Data model
Read-only consumers of:
- `site_settings` — `site_name`, `seo_description`, `seo_canonical_url`, `logo_url`
- `business_info` — `name`, `phone`, `email`, `social_links_json`
- `blog_posts` — `title`, `excerpt`, `cover_image`, `published_at`, `author`

## API surface
None — this is a render-time concern, not an HTTP endpoint. The output is visible in any view-source of a public page.

## Key files
- `app.py:6012-6029` — `Organization` + `WebSite` payload builder.
- `app.py:6453-6455` — substitution of `<!-- JSON_LD_INJECT -->` in the homepage shell.
- `templates/blog_post.html:74` — per-post `BlogPosting` JSON-LD.

## External deps
`json.dumps` (stdlib). No schema-validation library — Google's Rich Results Test is the closed-loop validator during development.

## Pitfalls
- Always `json.dumps(..., ensure_ascii=False)` so non-ASCII titles (Chinese, accented characters) render without `\uXXXX` escapes that break some validators.
- Escape `</script>` inside string values (replace `</` with `<\/`) or close-tag injection becomes an XSS vector.
- Schema.org enums are case-sensitive (`BlogPosting`, not `blogposting`).
- Don't emit JSON-LD that contradicts the visible page — Google penalises mismatches.

## Adaptation notes
- Add `Product`, `Event`, `FAQPage`, `Recipe`, `Service`, etc., by following the same template-injection pattern.
- For SPAs with no server-side render, inject the script via a route that returns the rendered HTML shell only — never via client-side JS, which crawlers may not execute.
- A future "schema registry" module could centralise type definitions; not needed below ~5 types.

## Adoption checklist
- [ ] Pick a unique placeholder comment (e.g. `<!-- JSON_LD_INJECT -->`).
- [ ] Build the payload server-side from DB rows, never from request input.
- [ ] Pass each payload through `json.dumps(..., ensure_ascii=False)` and `</` escaping.
- [ ] Validate via Google's Rich Results Test for at least one page of each type.
- [ ] Add a regression check that the injected block parses as valid JSON.
