# Section templates (display variants) — POC

How a web developer adds new ways to **display** a page section, **without** touching the section's
data or behavior. (Proof-of-concept: implemented for the **testimonials** section; clone the pattern
for the others.)

## The model — three separate layers

1. **Data (never touched to add a template).** Each section's content is loaded once via
   `/api/page-bundle` into a global on the public site (e.g. `testimonials`). The *shape* of that
   data is the section's **view-model contract** (below). A template only **receives** this — it
   must never query the DB.
2. **Template (what you add).** A renderer `function(items) → htmlString`, registered per section in
   `public/script.js` under `window.SECTION_TEMPLATES[<slug>][<variant>]`. The original look is the
   `default` variant.
3. **Selection.** The chosen variant per section is stored in `page_sections.settings.variant`,
   picked in **Admin → Page Layout → the “Layout” dropdown**. Unknown / absent / throwing →
   `default`, so a broken or missing template can never blank or break the page.

This generalizes the pattern the hero already uses (`hero_layout_mode`).

## View-model contracts (the data each template receives)

| Section | `items` shape |
|---|---|
| `testimonials` | `[{ id, reviewer_name, reviewer_role, content, rating, image_url }]` |
| _(add a row here as you add each section)_ | |

These fields come straight from `/api/page-bundle`. Adding a template never changes them — that's
the guarantee that templates can't break the DB connection.

## Add a template in 3 steps (example: a “carousel” for testimonials)

1. **Write the renderer** in `public/script.js`:
   ```js
   SECTION_TEMPLATES.testimonials.carousel = function (items) {
     return '<div class="tpl-testi-carousel">' +
       items.map(t => `<figure>…${t.content}… — ${escapeHtml(t.reviewer_name)}</figure>`).join('') +
       '</div>';
   };
   ```
   Consume only the contract fields; reuse the existing `escapeHtml` / `imgAttrs` helpers.
2. **Add any CSS** for your markup in `public/styles.css`, scoped to your own classes
   (the container carries `[data-tpl="<variant>"]` if you need to restyle it).
3. **Offer it in admin:** add `{ key: 'carousel', label: 'Carousel' }` to
   `SECTION_LAYOUTS.testimonials` in `public/admin/app-main.js`.

Then pick it in the **Layout** dropdown and reload the public site. The section's DB tables,
`/api/page-bundle`, ordering, and visibility are all untouched.

## Rules of the road

- A renderer takes `(items)` and returns an HTML string. **Never fetch data inside it.**
- Always keep a `default` variant — it is the fallback for an unknown or throwing variant.
- Variant keys: short slug-like strings, ≤ 40 chars (stored in `settings.variant`).
- The admin “Layout” dropdown saves by sending just `{ "variant": "<key>" }` to
  `PUT /admin/api/page-sections/<id>`, which **merges** it into the section's `settings` JSONB
  (other settings keys are preserved); `"default"`/empty clears the override.

## Where it lives (POC file map)

| Concern | File |
|---|---|
| Registry + dispatcher + `default`/`carousel` renderers | `public/script.js` (`SECTION_TEMPLATES`, `renderSectionTemplate`, `getSectionVariant`) |
| Carousel styles | `public/styles.css` (`.tpl-testi-*`, `#testimonials-grid[data-tpl="carousel"]`) |
| Admin “Layout” dropdown + manifest | `public/admin/app-main.js` (`SECTION_LAYOUTS`, `setSectionLayout`) + `templates/admin/tabs/_page-layout.html` |
| Persistence (merge `variant` into `settings`) | `admin/sitebuilder.py` (section PUT) |
| Storage | `page_sections.settings.variant` (existing JSONB column — no migration) |

## Server-rendered option (future)

For SEO or designer-authored HTML, a variant can instead be a Jinja partial
`templates/sections/<slug>/<variant>.html`, rendered with the same view-model server-side (the hero
already renders server-side via `_get_hero_markup()`). The contract — the data shape — stays
identical, so any section can graduate to server-rendering later without DB or admin changes.
