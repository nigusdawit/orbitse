# Admin panel — maintainer guide

The admin panel used to be one ~29k-line `dashboard.html`. It's now split into
small, single-responsibility files (no build step — plain CSS/JS + Jinja
`{% include %}`). This is the map.

## File layout

```
templates/admin/
  dashboard.html         ← the SHELL only (~1.7k lines): <head>, the inline
                            #admin-appearance-vars + __ADMIN_APPEARANCE__ bootstrap
                            (Jinja — must stay inline), <link>/<script src> tags,
                            the sidebar nav (with {% if %} feature gates), the
                            gx-drawer host + modals, and 66 {% include %} lines.
  tabs/_<id>.html        ← ONE file per tab panel (65 of them). Pure markup.
                            e.g. tabs/_pricing.html is the Pricing tab.
  README.md              ← this file

public/admin/            (served at /admin/<file> by the catch-all serve_static)
  base.css               ← :root tokens, resets, layout, shared .btn/.card/.data-table/.form-*
  theme.css              ← glass theme + the gx-* component kit + light/dark + appearance variants
  tabs.css               ← a few per-tab scoped styles (services / admin-chat / appearance)
  csrf.js                ← wraps window.fetch to auto-inject X-CSRF-Token (loads FIRST)
  app-main.js            ← the main controller: ~359 GLOBAL functions (switchTab, gx-drawer,
                            appearance AP, every loadX/saveX/editX, render helpers, merge-tag
                            editor, RTE, media picker). Loaded after csrf.js + the CDN libs.
  services.js            ← Services tab controller
  presentations.js       ← Presentations / Skills / LLM-provider tab loaders
```

Server routes live in `app.py` (being split into Flask blueprints under `admin/` —
see the de-monolith plan / Track B).

## Why these constraints (don't fight them)

- **No build step.** CSS/JS are plain files loaded with `<link>`/`<script src>`;
  the server stitches markup with Jinja `{% include %}` at request time. No
  bundler/framework. Edit a file, refresh, done.
- **JS functions are GLOBAL on purpose.** The markup calls them via inline
  `onclick="saveCard()"` (~616 handlers). So `app-main.js` etc. are **classic
  scripts, NOT ES modules** — `type="module"` would scope the functions and break
  every onclick. Keep new functions global (plain `function foo(){}` at top level).
- **Load order matters:** `csrf.js` → CDN libs → `app-main.js` → `services.js` →
  `presentations.js`. The CSRF wrapper must exist before any admin fetch.
- **Three things stay inline in `dashboard.html`** (they're Jinja, rendered per
  request — can't be static files): the `#admin-appearance-vars` `<style>`, the
  `window.__ADMIN_APPEARANCE__ = {{ appearance|tojson }}` bootstrap, and the
  sidebar's `{% if is_super_admin() / has_feature(...) %}` gates.

## How a tab works (the request → click flow)

1. **Sidebar button** in `dashboard.html`: `<button onclick="switchTab('pricing', this); ...">`
   — gated by `{% if is_super_admin() or has_feature('pricing') %}`.
2. **`switchTab('pricing')`** (in `app-main.js`) hides all `.tab-content`, shows
   `#tab-pricing`, and highlights the button.
3. **The panel** `#tab-pricing` lives in `tabs/_pricing.html`, included by the shell.
4. **A loader** like `loadPricing()` / `loadX()` (in `app-main.js`) fetches data
   from a route and renders into the panel. CRUD add/edit opens a **gx-drawer**
   (`gxOpenDrawer(...)`); save posts to the API; the CSRF header is auto-injected.
5. **The route** (`/admin/api/pricing`, etc.) is in `app.py` (→ a blueprint).

## How to add a new tab (recipe)

1. **Panel:** create `templates/admin/tabs/_mytab.html` with
   `<div id="tab-mytab" class="tab-content"> … use gx-* components … </div>`.
2. **Include it:** add `{% include "admin/tabs/_mytab.html" %}` in `dashboard.html`
   alongside the other includes.
3. **Sidebar button:** add a `<button class="tab-btn" onclick="switchTab('mytab', this); loadMyTab();" data-testid="tab-mytab">…</button>`
   in the right nav group (wrap in `{% if is_super_admin() or has_feature('…') %}`
   if it should be feature-gated).
4. **JS:** add `function loadMyTab(){…}` (and any `saveX/editX`) at top level in
   `app-main.js` (keep them global). Reuse `gxOpenDrawer`, `showToast`, the
   `gx-*` components.
5. **Route(s):** add the `/admin/api/mytab` endpoint(s) in `app.py` (or its
   blueprint). Use `@admin_required` (+ `_require_super_admin_role()` if super-admin-only).
6. **Styles:** reuse `gx-*` (in `theme.css`). Only add new CSS if a component
   doesn't exist — put tab-scoped rules in `tabs.css`.

## The gx-* component kit (use these; don't reinvent)

Defined in `theme.css`. The shared vocabulary every tab uses:
`gx-head`/`gx-title`/`gx-sub` (page header), `gx-card`, `gx-fieldset` +
`gx-grid-fields` (chunked forms), `gx-field`/`gx-label`/`gx-input`,
`gx-media-field` (URL+pick+upload+thumb), `gx-btn`/`gx-btn-primary`/`gx-btn-ghost`,
`gx-drawer` (slide-over for add/edit — via `gxOpenDrawer(title, node, {onSave})`),
`gx-table`/`gx-table-wrap` (responsive table), `gx-stat`/`gx-stats` (KPI tiles),
`gx-badge`(`-ok`/`-run`/`-err`), `gx-subtabs`, `gx-toolbar`, `gx-seg` (segmented),
`gx-stepper`, `gx-empty-rich`/`gx-skeleton`/`gx-error`/`gx-alert` (states).

## Appearance is no-code

The super-admin **Appearance** tab changes the whole admin's look (light/dark,
accent, density, typography, surface style, sidebar mode, presets, a11y) live and
persists it (migrations 0029/0030, `_admin_appearance()` + `PUT /admin/api/admin-appearance`).
Tokens flow from `#admin-appearance-vars` + `data-admin-*` attrs on `<html>` into
the `--admin-*` CSS variables, so most look changes need no code.

## Verifying changes

Boot the embedded-Postgres review server and drive it in a browser:
`uv run --python 3.12 --with pgserver --with flask … _live_glass.py` (admin/admin,
port 5070). Confirm the tab renders + works in **dark and light**, and that the
public/visitor site is unaffected. CSS/JS edits are live on refresh; template
edits need a server restart (Flask caches templates).
