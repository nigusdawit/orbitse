# Auto sitemap.xml + robots.txt from DB

## When to use
A multi-section CMS where the set of public URLs changes whenever the operator publishes new content (blog posts, generated pages, sections). You want search engines to discover new URLs within a crawl cycle without a manual deploy.

## Architecture
Two Flask routes generate XML/text on the fly from the live database:

- `GET /sitemap.xml` builds a `<urlset>` from four sources:
  1. Homepage `/` (highest priority).
  2. One entry per enabled `page_sections.slug` → `/<slug>` (gives crawlers a stable landing per section even though the homepage snap-scrolls).
  3. One entry per `blog_posts` where `status='published'` → `/blog/<slug>`.
  4. One entry per `generated_pages` where `status='published'` → `/page/<slug>`.
- `GET /robots.txt` returns a small allow-all-but-admin policy and points at `Sitemap: <SITE_URL>/sitemap.xml`.

The canonical base URL is read from `site_settings.seo_canonical_url`, with `request.url_root` as fallback so dev previews and freshly cloned installs work without configuration.

## Data model
Read-only consumers of:
- `site_settings` — `seo_canonical_url TEXT`
- `page_sections` — `slug TEXT`, `enabled BOOLEAN`, `updated_at TIMESTAMPTZ` (lastmod)
- `blog_posts` — `slug`, `status`, `updated_at`
- `generated_pages` — `slug`, `status`, `updated_at`

No new tables.

## API surface
- `GET /sitemap.xml` → `application/xml`, public, no auth.
- `GET /robots.txt` → `text/plain`, public, no auth.

## Key files
- `app.py:7683` — `sitemap_xml()` route.
- `app.py:7791` — `robots_txt()` route.
- `app.py:7691-7700` — canonical URL resolution.

## External deps
None beyond the stdlib (`xml.sax.saxutils.escape` for safe XML). No third-party sitemap library.

## Pitfalls
- Forgetting to escape `&` in slugs produces invalid XML — always run titles/URLs through XML escaping.
- Cache-Control on these routes should be short (≤1 h). They are cheap to regenerate and stale sitemaps delay indexing.
- `request.url_root` returns `http://` behind a TLS-terminating proxy unless `ProxyFix` is in place; configure that first or the sitemap will advertise insecure URLs.
- Don't list draft / unpublished rows. The `status='published'` filter is the only line standing between an editor and an accidental leak.

## Adaptation notes
- Add new content types by appending another query block — each only needs `slug`, `updated_at`, and a URL prefix.
- For very large sites (>50 k URLs), split into a sitemap index and per-type sub-sitemaps.
- `lastmod` is optional; emit it only when you have a reliable `updated_at`. Lying about freshness wastes crawl budget.

## Adoption checklist
- [ ] Copy the two routes and the canonical-URL helper.
- [ ] Add a `seo_canonical_url` column (or read from env if no settings table).
- [ ] Ensure every content-type table queried has a published/enabled flag and `updated_at`.
- [ ] Verify `ProxyFix` is wired before `app.run` so URLs come out as `https://`.
- [ ] Submit the new sitemap URL in Google Search Console / Bing Webmaster.
