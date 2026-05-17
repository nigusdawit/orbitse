# Page Section Registry (Drag-Reorder + Visibility Toggle for Landing Sections)

**Category:** Content Management
**Related:** `content/02-custom-section-templates.md`, `content/03-drag-and-drop-reordering.md`, `admin-tooling/...`

## When to use
You have a one-page landing site composed of well-known sections (hero, highlights, experiences, pricing, testimonials, team, FAQ, blog, business info, …) and you want the site operator to drag those sections into any order AND toggle individual sections on/off — without code changes, and without losing the ability to inject new built-in sections in future code releases.

## Architecture
- **One DB row per section** in `page_sections`. Both built-in sections (`hero`, `gallery`, `testimonials`, …) and admin-created custom sections (see skill #2) live in the same table — the registry is unified so the AI prompt, the public renderer, and the admin reorder UI all see one list.
- **Slug is the contract.** Each row's `slug` maps to a DOM id on the public page via a server-side helper (`_resolve_section_dom_id`). The AI's `scrollToSection` command and the admin's drag list both reference slugs.
- **Built-in vs custom is implicit.** Built-in slugs are documented in code; anything with `slug='custom-<id>'` (or with a matching `custom_sections` row) is admin-created. No `is_builtin` column.
- **Reorder = rewrite `sort_order` for the whole list.** Atomic PUT that accepts an ordered array of ids; server numbers them 0..N.
- **Visibility = a single `enabled` boolean.** Disabled rows are kept in the DB (so re-enabling preserves order) and simply skipped during render.
- **Two-phase render on the public site.** The HTML ships with all built-in sections in their default order; on load, `applySectionOrder()` re-appends the section elements in `pageSections` array order and applies `display:none` to disabled ones.

## Data model
Table `page_sections`:

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `slug` UNIQUE | Matches a known built-in (`hero`, `gallery`, `experiences`, `pricing`, `testimonials`, `team`, `faq`, `blog`, `business-info`, `services`, …) OR `custom-<id>` |
| `section_type` | `'builtin'` or `'custom'` — informational, used by admin UI to gate edit affordances |
| `enabled` BOOLEAN | False hides the section without losing its position |
| `sort_order` INTEGER | 0-based display order |
| `seo_title`, `seo_description`, `seo_image` | Per-section SEO overrides (optional) |

The registry is loaded once on app boot and again on every admin write; the public site fetches it via `/api/page-sections`.

## API surface
- `GET /api/page-sections` — public read: only `enabled=true`, ordered by `sort_order`. The frontend uses this to drive `applySectionOrder()`.
- `GET /admin/api/page-sections` — admin read: full list including disabled rows.
- `PUT /admin/api/page-sections/reorder` — body `{ids: [3,7,1,4,...]}`; server `UPDATE ... SET sort_order = array_position(...)` in a single transaction.
- `PATCH /admin/api/page-sections/<id>` — body `{enabled: bool}` (or SEO field updates). The reorder endpoint and the patch endpoint are deliberately separate so a visibility flip never accidentally re-orders.

## Key files
- `app.py` — `page_sections` table init, list/reorder/patch routes, `_resolve_section_dom_id` (slug → DOM id mapping), `LANDING_PAGE_LAYOUT` prompt block (~line 9005) that injects the current section order into the AI system prompt
- `public/script.js` — `applySectionOrder()` (~line 3850): iterates `pageSections` and re-appends each `#section-<slug>` element to the landing container in DB order; toggles `display` based on `enabled`
- `public/index.html` — default HTML markup with all built-in sections present in source order

## External dependencies
None — pure DB + DOM reflow.

## Pitfalls
- **DOM ids must exist for every slug** the server ever returns. If the AI prompt advertises a slug whose `#section-<slug>` element isn't in `index.html`, `scrollToSection` is a no-op. Keep the registry of built-in slugs in code in lockstep with `index.html`.
- **Custom sections require a separate render pass** before reorder runs — they don't exist in the source HTML. `renderCustomSections()` creates the DOM nodes, then `applySectionOrder()` places them. Order matters in `script.js` init.
- **Don't trust client-supplied `sort_order`** in the reorder payload — only use the position of each id in the array. Otherwise two admins editing concurrently can corrupt the sequence.
- **Disabled rows still consume slugs** — when displaying "which sections is the AI allowed to scroll to" in the prompt, mark them DISABLED instead of hiding so the AI doesn't try to use them.

## Adaptation notes
- To add a new built-in section: add a row to `page_sections` in the init migration with a fresh slug + default `sort_order`, add the matching `<section id="section-<slug>">` to `index.html`, add the slug to the `_resolve_section_dom_id` map, and (optionally) inject it into the AI's LANDING_PAGE_LAYOUT block.
- For multi-tenant: scope the table by `tenant_id` and add it to the unique constraint on `slug`.
- Two-phase render isn't required if you can server-render the whole landing page — but the reorder UX feels snappier when the DOM is already populated and you just shuffle nodes.

## Adoption checklist
- [ ] `page_sections` table with `slug`, `enabled`, `sort_order`
- [ ] Slug → DOM id resolver on the server
- [ ] Public read endpoint (enabled only) + admin endpoints (reorder, patch)
- [ ] Frontend `applySectionOrder()` that runs AFTER custom sections render
- [ ] AI prompt block that lists current section order with enabled/disabled flags
