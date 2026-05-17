# Theme / Color Editor (Live CSS-Variable Swapping)

**Category:** Content Management
**Related:** `content/07-glassmorphic-design-system.md`, `content/09-loading-screen.md`

## When to use
You want the site operator to change brand colors, fonts, motion, and surface treatments from an admin UI — see the result live in a preview without reload, persist the active theme to the DB, and have the public site first-paint with the right values (no FOUC).

## Architecture
- **Theme = a row in `site_themes`** with palette + fonts + preset values (one active at a time). Multiple themes can be saved; the admin picks which is active.
- **CSS custom properties are the runtime substrate.** Every component reads `var(--color-accent)`, `var(--font-serif)`, etc. — never hardcoded hex values. Swapping a theme = setting new values on `:root`.
- **First paint via server-side `<style>` injection.** `_build_theme_vars_style()` builds a `<style id="theme-vars-injected">:root { --color-accent: ...; --font-serif: ...; ... }</style>` block and injects it into the served `<head>`. No FOUC because the variables exist before the first paint.
- **Live edit via `document.documentElement.style.setProperty()`.** `loadAndApplyTheme()` re-fetches `/api/theme` and applies every key to the root element. Companion data attributes (`data-card-style`, `data-photo-filter`, …) are re-set in the same pass.
- **Fonts are loaded dynamically.** Server emits a single `<link rel="stylesheet">` for exactly the active theme's serif+sans pair (built by `_build_active_font_link`) instead of always pulling Playfair+DM Sans. Eliminates wasted font downloads when the active pair is different.
- **RGB triples for tinted overlays.** `--color-bg` is a hex; `--color-bg-rgb` is the same color as a space-separated RGB triple, so `rgba()` overlays (loading screen, modal backdrops) can re-tint themselves when the theme changes.

## Data model
Table `site_themes`:

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `name` | Operator label |
| `palette_json` JSONB | `{color_bg, color_section_1, color_section_2, color_accent, color_text, glass_bg, glass_border, ...}` |
| `fonts_json` JSONB | `{serif, sans}` (Google Fonts family names) |
| `status` | `draft` / `archived` |
| `is_active` BOOLEAN | Only one row may be active; enforced in the save handler |
| `created_at`, `updated_at` | |

Preset values (`card_style`, `photo_filter`, `easing`, `loading_mode`, `density`, `header_align`) can either be additional columns or extra keys inside `palette_json` — pick a convention and stick with it.

## API surface
- `GET /api/theme` — public read of the active theme; small, cacheable.
- `GET /admin/api/themes` — admin list of all saved themes.
- `PUT /admin/api/theme` — admin save (activate + edit). Server enforces `is_active` exclusivity.
- `POST /admin/api/themes` / `DELETE /admin/api/themes/<id>` — admin create / archive.

## Key files
- `app.py` — `_build_theme_vars_style()` (~line 6057): assembles the first-paint `<style>` block; `_build_active_font_link()`: emits the right Google Fonts link; theme routes + activation logic
- `public/script.js` — `loadAndApplyTheme()` (~line 4900): live-edit handler that re-sets CSS vars + data attributes
- `public/styles.css` — all components use `var(--token)` references, never hardcoded values
- `templates/admin/dashboard.html` — Theme tab UI: color pickers, font dropdowns, preset selectors; on save, fires a `loadAndApplyTheme()` event so the live site preview updates

## External dependencies
- Google Fonts CDN for typography (dynamically constructed URL).
- No theming library — pure CSS custom properties.

## Pitfalls
- **Server-side injection MUST run before the first `<style>`/`<link>` in `<head>`.** Otherwise the cascade order means defaults win and the theme appears not to apply.
- **Activation must be atomic.** `UPDATE site_themes SET is_active = FALSE; UPDATE site_themes SET is_active = TRUE WHERE id = ?;` in one transaction — otherwise a crash mid-save leaves zero or two active themes.
- **Live edit must update tinted-overlay variables together.** Changing `--color-bg` without also updating `--color-bg-rgb` leaves the loading screen flashing the old tint.
- **Don't cache `/api/theme` aggressively.** The admin expects edits to be visible on a fresh tab within seconds — pair short `max-age` with `stale-while-revalidate`.
- **Font loads block first paint** when injected via `<link>` in head. Acceptable trade-off for typographic correctness; mitigate with `font-display: swap` in the font URL.
- **Color contrast can collapse** when an operator picks a near-white accent on a light theme. Validate WCAG contrast at save time, or warn in the admin UI.

## Adaptation notes
- For multi-tenant: scope `site_themes` by `tenant_id` and key `is_active` on `(tenant_id)`.
- For dark/light mode pairs, store both palettes in one theme row and pick by `prefers-color-scheme` or an explicit `data-color-scheme` attribute on `<html>`.
- To support per-page theme overrides (e.g. a blog post in a different palette), set the same CSS vars on a page-level wrapper instead of `:root`.

## Adoption checklist
- [ ] Every visual rule reads CSS vars (no hardcoded hex)
- [ ] `site_themes` table with `is_active` exclusivity enforced in a transaction
- [ ] Server-side `<style>` injection ordered BEFORE any other CSS in `<head>`
- [ ] First-paint also sets `data-*` preset attributes on `<html>`
- [ ] Live-edit handler updates CSS vars AND data attributes in one pass
- [ ] RGB-triple companion variables for any color used inside `rgba()`
- [ ] Dynamic Google Fonts link built from the active theme's font pair
