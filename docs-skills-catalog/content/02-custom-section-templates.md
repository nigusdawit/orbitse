# Custom Section Template Library (Admin-Authored Landing Sections)

**Category:** Content Management
**Related:** `content/01-page-section-registry.md`, `content/03-drag-and-drop-reordering.md`

## When to use
You want the site operator to add brand-new sections to the landing page from the admin UI — not just enable/disable a fixed catalog. Two flavors are needed: "layout" templates where the operator authors the items (cards, text, gallery, CTA, stats, icon features), and "data-showcase" templates that automatically pull from existing libraries (events, products, services, podcast, video gallery) so the operator doesn't re-enter content that already lives elsewhere.

## Architecture
- **Two tables:** `custom_sections` (one row per section, declares which template to render with) and `custom_section_items` (zero+ rows per section, holds the per-item content for layout templates).
- **`template` is a string enum** on `custom_sections`. The frontend renderer switches on it to pick markup; the admin UI switches on it to show the right edit form.
- **Layout templates own their items.** `cards_grid`, `text_content`, `image_gallery`, `cta_banner`, `stats_counter`, `icon_features` — the admin authors `custom_section_items` rows (title, subtitle, description, image, icon, link).
- **Data-showcase templates ignore items.** `events`, `rsvp_form`, `video_gallery`, `podcast`, `products`, `services` — render is driven by the existing tables for those features. Admin UI hides the "items" editor for these.
- **One special-case overload:** the `rsvp_form` template stores a target event slug in `custom_sections.subtitle` because it needs one piece of config but doesn't deserve its own column. Pragmatic, ugly, works.
- **Each custom section gets a `page_sections` row** (slug `custom-<id>`) so it participates in the same drag-reorder + visibility toggle system as built-ins. The two tables are linked by slug, not FK — keeps the registry uniform.

## Data model
Table `custom_sections`:

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `slug` | Mirror of `page_sections.slug = 'custom-<id>'` |
| `title` | Section heading |
| `subtitle` | Section subtitle / eyebrow — also the overload field for `rsvp_form` |
| `template` | One of the 11 template names |
| `enabled` BOOLEAN | Mirrors `page_sections.enabled` |
| `sort_order` INTEGER | Mirrors `page_sections.sort_order` |
| `theme_data` JSONB | Per-section style overrides (optional) |

Table `custom_section_items`:

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `section_id` FK | ON DELETE CASCADE |
| `title`, `subtitle`, `description` | Free text |
| `image_url`, `icon` | Visual assets (lucide icon name, or uploaded image) |
| `link_url`, `link_text` | Optional CTA |
| `sort_order` INTEGER | Drag-reorder within the section |

## API surface
- `GET /api/custom-sections` — public read of enabled sections + their items.
- `GET /admin/api/custom-sections` / `POST` / `PUT /<id>` / `DELETE /<id>` — admin CRUD. Create also inserts the matching `page_sections` row.
- `POST /admin/api/custom-sections/<id>/items` / `PUT /items/<id>` / `DELETE /items/<id>` — item CRUD; blocked server-side when the section's template is a data-showcase one.
- `PUT /admin/api/custom-sections/<id>/items/reorder` — same `{ids:[...]}` payload pattern as the global reorder skill.

## Key files
- `app.py` — `custom_sections` / `custom_section_items` table init, CRUD routes, template-name validation list, paired `page_sections` row maintenance (create/delete cascade)
- `public/script.js` — `renderCustomSections()` (~line 3450): for each section, switch on `template` and call the matching renderer; runs BEFORE `applySectionOrder()` so the nodes exist when the reorder pass runs
- `templates/admin/dashboard.html` — Page Layout tab UI: template picker dropdown, layout-vs-showcase branch that hides the items editor

## External dependencies
None new — reuses the same Sortable.js drag-reorder, lucide icons, image upload pipeline already in use elsewhere.

## Pitfalls
- **Renaming a template enum is a migration.** The string lives in DB rows; rename it in code without a `UPDATE custom_sections SET template = ...` and the renderer falls through to a blank section.
- **Data-showcase templates need their items endpoints BLOCKED server-side.** Otherwise an admin (or a stale tab) can POST items that the renderer ignores — silent data loss.
- **`page_sections` and `custom_sections` can drift.** Deleting a custom section must also delete the paired `page_sections` row, and vice versa. Wrap both in one transaction.
- **Lucide icons load via CDN** — guard against missing icon names with a fallback glyph; don't blow up the render.
- **Image gallery templates can balloon page weight.** Consider lazy-loading and a per-section image-count cap.

## Adaptation notes
- Adding a new layout template = add the enum string, add a renderer branch in `script.js`, add an admin editor for the items shape if it differs.
- Adding a new data-showcase template = add the enum string, add a renderer branch that fetches the existing table, and add the "hide items editor" guard for the new name.
- For more structured per-template config, replace the `subtitle` overload with a JSONB `template_config` column.

## Adoption checklist
- [ ] `custom_sections` + `custom_section_items` tables
- [ ] Template enum + server-side validation (reject unknown names)
- [ ] Paired `page_sections` row created/deleted in the same transaction
- [ ] Admin UI branches by template (layout vs data-showcase)
- [ ] Public renderer switches on template name; runs before section-order pass
- [ ] Items endpoints blocked for data-showcase templates
