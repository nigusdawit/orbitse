# Glassmorphic Design System (Backdrop-Filter Tokens + Surface Presets)

**Category:** Content Management
**Related:** `content/06-snap-scroll-landing.md`, `content/08-theme-color-editor.md`

## When to use
You want a consistent frosted-glass aesthetic across cards, modals, nav, chat panels, and loading overlays — driven by a handful of CSS custom properties so the operator can dial the look (glass blur, border opacity, radius) and switch between named surface styles (glass, brutal, minimal, editorial) without touching component CSS.

## Architecture
- **Two layers of customization.** Low-level tokens (`--glass-bg`, `--glass-border`, `--glass-blur`, `--radius`) shared by every card-shaped surface; high-level "surface treatment presets" (`[data-card-style]`, `[data-photo-filter]`, `[data-easing]`, `[data-loading-mode]`) on `<html>` that swap the personality of the whole site in one attribute change.
- **Presets are CSS-only.** No JS conditional rendering — each preset is a `[data-card-style="X"] :is(.card1, .card2, ...) { ... }` rule that overrides the per-component defaults. Adding a new card class = appending it once to the shared `:is(...)` group; all four presets pick it up automatically.
- **One canonical card-class group.** A long but exhaustive `:is(...)` selector lists every public-site card class (`.event-card`, `.blog-card`, `.experience-card`, `.gallery-card`, `.sphere-card`, ...). Admin-only / utility cards are intentionally excluded.
- **First-paint + live-edit symmetry.** Server sets `data-card-style` / `data-photo-filter` / etc. on `<html>` from theme settings; `script.js` re-applies on theme save so the admin doesn't need a reload.
- **Photo filter applies to images + CSS background-images.** Two arms of the selector — `img:not(<opt-out list>)` and `:is(<background-image surface list>)` — both get the same `filter:` value. Opt-out via `.no-photo-filter` or `[data-no-photo-filter]` for brand marks/logos/avatars.
- **Loading mode preset hides parts of the boot overlay** (`logo_only`, `spinner_only`, `fade_only`) without altering the loading screen markup — display:none rules per mode.

## Data model
Tokens and preset values live in `site_themes` / theme tables (see skill #8):
- `theme_glass_blur`, `theme_glass_bg`, `theme_glass_border`, `theme_radius`, `theme_loading_bg_alpha` — token scalars
- `theme_card_style` ∈ {`editorial`, `glass`, `brutal`, `minimal`} — preset selector
- `theme_photo_filter` ∈ {`none`, `warm`, `cool`, `bw`, `grain`}
- `theme_easing` — named cubic-bezier, exposed as `--ease-active` (legacy `--ease-smooth` aliased to it)
- `theme_loading_mode` ∈ {`default`, `logo_only`, `spinner_only`, `fade_only`}

## API surface
- `GET /api/theme` — returns active tokens + preset values for first-paint and runtime.
- `PUT /admin/api/theme` — admin edits; response triggers `script.js` to update CSS variables AND `data-*` attributes live.

## Key files
- `public/styles.css` §2 (`:root` tokens, ~line 76), §2b (loading screen, ~line 145), §2c (surface treatment presets, ~line 236) — all four presets + photo-filter rules + loading-mode toggles
- `app.py` — `_build_theme_vars_style()` injects `<style id="theme-vars-injected">` with the current token values; server also sets `data-card-style` / `data-photo-filter` / `data-loading-mode` / `data-density` / `data-header-align` on `<html>` for first paint
- `public/script.js` — live-edit handler that re-applies CSS vars and re-sets data attributes when the admin saves theme changes

## External dependencies
- **`backdrop-filter`** — supported in every evergreen browser including Safari (which needs `-webkit-backdrop-filter`).
- Tiny inline SVG noise (data URL) for the `grain` photo filter — no external asset.

## Pitfalls
- **`backdrop-filter` is expensive** — limit it to clearly bounded surfaces (cards, modals, nav). Applying it to a full-screen overlay over a video background drops frame rate on mid-range mobile.
- **Don't stack backdrop-filter through ancestors** — only the innermost element's filter is applied, and intermediate filters create stacking contexts that break z-index assumptions.
- **The photo-filter opt-out list must include EVERY brand mark class.** Missing one and the site logo gets the grain treatment. Use `[class*="logo"]` as a catch-all in addition to the explicit list.
- **Grain overlay needs `position: relative` on the wrapper** — the `::after` pseudo-element it draws on uses `position: absolute; inset: 0`.
- **Live-edit must update BOTH CSS vars AND data attributes.** Presets like `brutal` swap `border-radius` and `box-shadow` via the data attribute, not via a variable, so editing only the variables leaves the preset stuck.
- **Easing token must survive aliasing.** Existing CSS rules reference `var(--ease-smooth)` in dozens of places; the system aliases `--ease-smooth: var(--ease-active)` so swapping `--ease-active` re-easings the whole site without touching every rule.

## Adaptation notes
- To add a new preset: pick a name, write the override block `[data-card-style="<name>"] :is(<card group>) { ... }`, add it to the admin dropdown. No JS changes.
- Adding a new card class anywhere on the site: append the class to the four `:is(...)` groups in §2c. Without this it won't participate in card-style presets (and the admin's preset toggle will appear broken to them).
- For light-mode support, define the same tokens with light-mode values and add a `[data-color-scheme="light"]` parent attribute — the per-component rules stay unchanged.

## Adoption checklist
- [ ] Core tokens defined once in `:root`
- [ ] Shared card-class group selector (single source of truth)
- [ ] Per-preset override blocks for each `data-card-style` value
- [ ] Photo-filter selector with explicit opt-out list for brand marks
- [ ] First-paint injection of all `data-*` attributes from theme settings
- [ ] Live-edit handler that updates CSS vars AND data attributes
- [ ] Easing alias so legacy `--ease-smooth` references pick up the active value
