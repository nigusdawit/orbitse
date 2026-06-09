# Section templates (display variants)

How a web developer adds new ways to **display** a page section, **without** touching the section's
data or behavior. Two authoring models — **A** (client-side JS template; sample testimonials/carousel)
and **B** (server-rendered Jinja partial → SEO; sample team/spotlight + the full-featured
team/showcase). Both share one selection mechanism (`page_sections.settings.variant`), one admin
picker, and one manifest. **See "Full capability reference" at the bottom** for custom fields, options,
JS hooks, and scoped assets.

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

## Option B — server-rendered Jinja partials (IMPLEMENTED: team / spotlight)

For SEO or designer-authored HTML, a variant can be a **Jinja partial** rendered server-side into the
page source, instead of a JS function. Same selection (`settings.variant`), same admin dropdown, same
fallback — only the authoring + render location differ. Sample: the **team** section's `spotlight`.

- **Partial:** `templates/sections/team/spotlight.html` — plain HTML/Jinja, receives the view-model
  `members: [{ name, title, bio, image_url }]` (Jinja autoescaping on). Its root carries
  `data-ssr-section="team"`.
- **Render + inject:** `app._render_section_partial(slug)` reads `settings.variant` and renders
  `templates/sections/<slug>/<variant>.html` with the view-model; `_render_app_shell_response`
  replaces a `<!-- SECTION_TEAM_INJECT -->` placeholder in `public/index.html`, so the markup is in
  the **initial HTML source (SEO)**. Registry: `app._SSR_SECTION_VARIANTS`; data loaders:
  `app._section_view_model(slug)`.
- **Client coordination:** `renderTeam()` skips when it sees `[data-ssr-section]`. `default` stays
  client-rendered (the placeholder is replaced with '').
- **Fail-safe:** disabled / `default` / missing partial / any error → '' → the client renders the
  default; a missing placeholder makes the inject a harmless no-op.

### Add a server-rendered (Option B) variant
1. Drop `templates/sections/<slug>/<variant>.html` (root gets `data-ssr-section="<slug>"`).
2. Register it: add `<variant>` to `app._SSR_SECTION_VARIANTS[<slug>]` (+ a loader branch in
   `app._section_view_model(<slug>)` if the section isn't wired yet).
3. Add a `<!-- SECTION_<SLUG>_INJECT -->` placeholder in the section's shell in `public/index.html`
   and a matching `.replace(...)` in `_render_app_shell_response`; have the client renderer early-skip
   on `[data-ssr-section]`.
4. Offer it in `SECTION_LAYOUTS.<slug>` (admin dropdown).

## A vs B — pick per section (both ship as samples)
- **A (JS template)** — fastest, no round-trip, fits the existing client render; not in initial source
  (weaker SEO). Sample: **testimonials / carousel**.
- **B (Jinja partial)** — designer-friendly HTML, **server-rendered = SEO**; the section moves to
  server-render. Sample: **team / spotlight**. Mirrors the hero's `_get_hero_markup()` precedent.

Both share the same `settings.variant` storage + admin picker, so a section can switch models later
without DB or admin changes.

---

# Full capability reference (Option B)

Everything below is wired into **`app.SECTION_TEMPLATE_REGISTRY`** — the single source of truth. A
section entry = `{ loader, variants }`; a variant = `{ label, options, item_fields, client? }`. The
manifest at **`GET /admin/api/section-templates`** exposes it to the admin UI. All paths are
**fail-safe** (any miss/error → the section's client default; a missing placeholder → a no-op).

### What a variant can do
| Capability | How | Where |
|---|---|---|
| **Any look / layout / CSS animation** | arbitrary HTML/Jinja + CSS; reuse the site's `.fade-in-view` for scroll-reveal | the partial + CSS |
| **Images / video** | `<img>`/`<video>`/`<iframe>`; for per-item media, read a custom field (below) | the partial |
| **Per-item custom fields** | declare `item_fields:[{key,label,type}]`; stored in the item table's `extra` JSONB; admin auto-renders inputs; template reads `m.extra.<key>` | registry + admin form |
| **Per-variant options** | declare `options:[{key,label,type,choices,default}]`; admin auto-renders a form (⚙); stored in `settings.variant_options`; passed to the partial as `options` | registry + options drawer |
| **JS behavior** (autoplay, lightbox, counters…) | partial root gets `data-tpl-init="<name>"` + `data-tpl-options`; a JS asset registers `window.SECTION_TEMPLATE_INIT[name]=fn`; the script.js dispatcher runs it once per root | partial + JS asset |
| **Scoped CSS/JS assets** | `public/sections/<slug>/<variant>.{css,js}` — auto-injected only when that variant is active | files on disk |

### Add a fully-featured server-rendered variant (the showcase recipe)
1. **Registry** (`app.SECTION_TEMPLATE_REGISTRY[<slug>].variants.<variant>`): set `label`, and any
   `options` / `item_fields` schemas. (If the section isn't wired yet, also add its `loader`.)
2. **Partial** `templates/sections/<slug>/<variant>.html`: root carries
   `data-ssr-section="<slug>" data-tpl-init="<name>" data-tpl-options='{{ options | tojson }}'`.
   Read `items` (+ `m.extra.<key>`) and `options.<key>`. Jinja autoescapes — safe by default.
3. **Assets** (optional): `public/sections/<slug>/<variant>.css` and `.js`. The JS does
   `(window.SECTION_TEMPLATE_INIT ||= {}).<name> = function(rootEl, options){…}`.
4. **Placeholder**: ensure `<!-- SECTION_INJECT:<slug> -->` sits in the section's shell in
   `public/index.html` (one-time per section), and the client renderer early-skips on
   `[data-ssr-section]`.
That's it — the admin Layout dropdown, the ⚙ options form, and the per-item custom-field inputs all
appear automatically from the manifest. Pick the variant, set options, fill fields, reload.

### Reference files
| Concern | File |
|---|---|
| Registry + render + inject + manifest | `app.py` (`SECTION_TEMPLATE_REGISTRY`, `_render_section_partial`, `_render_app_shell_response`, `admin_section_templates`) |
| JS init dispatcher | `public/script.js` (`runSectionTemplateInit`, `SECTION_TEMPLATE_INIT`) |
| Admin UI (dropdown / options / custom fields) | `public/admin/app-main.js` (`getSectionTemplates`, `openSectionOptions`, `_loadTeamExtraFields`) |
| Persistence (variant / variant_options merge) | `admin/sitebuilder.py` (section PUT) ; per-item `extra` → `admin/content.py` (team CRUD) |
| Storage | `page_sections.settings.{variant,variant_options}` ; `<item table>.extra` JSONB |
| Samples | `templates/sections/team/{spotlight,showcase}.html` + `public/sections/team/showcase.{css,js}` |

### The one boundary to keep
Never let untrusted users upload raw Jinja/JS (SSTI / XSS = code execution). Authoring partials +
assets is a **trusted-dev / deploy** action. Non-devs customize via the **safe structured knobs**
(options + custom fields), never raw template code.
