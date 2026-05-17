# Loading Screen (Theme-Tinted Glass Overlay with Shimmer + Fade)

**Category:** Content Management
**Related:** `content/07-glassmorphic-design-system.md`, `content/08-theme-color-editor.md`

## When to use
You want a polished boot overlay that hides the initial render flash while the public site fetches its data, matches the active theme palette (so it never flashes the wrong color), shows the site's brand initials, and fades out with a soft scale transition the moment the page is ready.

## Architecture
- **Single fixed full-viewport `.loading-screen` div** in `index.html` markup. It's the first thing rendered so it's visible immediately on first paint.
- **Theme-tinted background.** Uses `rgb(var(--color-bg-rgb) / var(--loading-bg-alpha))` — the RGB triple companion variable lets the overlay re-tint when the active theme background changes, and the alpha is admin-configurable.
- **Glass panel inside the overlay.** Inherits the global `--glass-bg` / `--glass-border` / `--glass-blur` / `--radius` tokens so it visually matches the site's card system.
- **Three animated elements**, each with a per-element preset:
  - `.loading-logo-badge` — circular badge with the site's initials, pulse animation
  - `.loading-site-name` — site name in the serif font
  - `.loading-shimmer` — thin bar with a traveling gradient in the active accent color
- **Server-side injection of initials + name.** Placeholders `LOADING_INITIALS_INJECT` / `LOADING_NAME_INJECT` in `index.html` are replaced by the server from site settings so first paint has the right brand even before JS runs.
- **Fade-out via class swap.** `hideLoadingScreen()` adds `.fade-out` (opacity 0 + `scale(1.02)`), then sets `display: none` after the 600ms transition. Pointer events disabled during fade so a click on a CTA underneath doesn't accidentally fire while the overlay is still partially visible.
- **Loading-mode preset honored.** `[data-loading-mode]` on `<html>` can hide individual elements (logo only, spinner only, fade only) without altering the markup — see skill #7.

## Data model
No dedicated table. Driven by:
- `site_settings.site_name` (or equivalent) — initials are derived client-side / server-side
- `theme_loading_bg_alpha`, `theme_loading_mode` — from the active theme (skill #8)
- `--color-bg-rgb`, `--color-accent`, `--glass-*`, `--radius` — global tokens

## API surface
None of its own — reads from the existing site-settings + theme endpoints.

## Key files
- `public/styles.css` §2b (~line 145) — `.loading-screen`, `.loading-panel`, `.loading-logo-badge`, `.loading-site-name`, `.loading-shimmer`, `.loading-shimmer-bar`, `@keyframes loadingPulse`, `@keyframes loadingShimmer`
- `public/script.js` — `hideLoadingScreen()` (~line 331): adds `.fade-out`, sets `display: none` after 600ms (matched to `--transition-medium`)
- `app.py` — `_build_loading_initials_and_name()` (~line 6289): replaces `LOADING_INITIALS_INJECT` / `LOADING_NAME_INJECT` placeholders before serving `index.html`
- `public/index.html` — loading screen markup with the placeholders

## External dependencies
None.

## Pitfalls
- **First-paint correctness depends on token order.** The theme `<style>` block must be injected before the loading screen's CSS so `--color-bg-rgb` / `--loading-bg-alpha` are defined when the overlay paints.
- **`display: none` after fade, not during.** Setting `display: none` immediately kills the transition entirely; you need a `transitionend` listener or a timer matched to the transition duration.
- **600ms timer must match `--transition-medium`.** If they drift, the overlay either disappears mid-fade (jarring) or sticks around as a non-interactive ghost (eats clicks).
- **`pointer-events: none` on `.fade-out` is required.** Otherwise the half-transparent overlay still blocks clicks for 600ms after the page is "ready".
- **Don't gate `hideLoadingScreen()` on a single fetch.** Wait for the aggregate page-bundle fetch (or `Promise.all` of critical loads) — otherwise the overlay fades just as content is still rendering and the visitor sees a second flash.
- **Initials with non-ASCII names.** Slicing the first character of `"Östra"` works fine in JS, but the server-side injection must use unicode-aware slicing (`s[0]` on a Python str is safe; byte-level slicing isn't).
- **Loading-mode `fade_only` strips the panel entirely** — make sure the `.loading-panel` rule that disables background/border/box-shadow/padding is present, otherwise an empty glass panel still shows.

## Adaptation notes
- For very fast cached loads, the loading screen can flash in and out distractingly. Add a min-display threshold (e.g. don't fade until at least 400ms have elapsed) so the overlay always feels intentional.
- Replace initials with an SVG logo by changing `.loading-logo-badge` content — keep the badge sizing for consistent layout.
- For SSR-rendered pages where content is already present, skip the overlay entirely or use `data-loading-mode="fade_only"` for a minimal tint.
- To localize the site name format (RTL languages, scripts where "initials" don't make sense), inject the full name only and skip the initials badge.

## Adoption checklist
- [ ] Single `.loading-screen` div as the first element in `<body>`
- [ ] Theme-tinted background via `rgb(var(--color-bg-rgb) / var(--loading-bg-alpha))`
- [ ] Inner panel uses the global glass tokens
- [ ] Server-side initials + name injection so first paint has correct brand
- [ ] `hideLoadingScreen()` waits for the aggregate page-bundle, not a single fetch
- [ ] Fade-out via class swap + `display: none` after a timer matched to the CSS transition
- [ ] `pointer-events: none` while fading so the overlay doesn't eat clicks
- [ ] `[data-loading-mode]` preset honored (logo only / spinner only / fade only)
