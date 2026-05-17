# Snap-Scroll Landing Template (CSS Scroll-Snap + IntersectionObserver Fades)

**Category:** Content Management
**Related:** `content/01-page-section-registry.md`, `content/07-glassmorphic-design-system.md`

## When to use
You want a one-page landing site where each section feels like a discrete "slide" — the page snaps from section to section as the visitor scrolls, with each section fading in as it enters the viewport. Suitable for marketing one-pagers, brochure sites, portfolios, hospitality/real-estate sites.

## Architecture
- **CSS scroll-snap does the heavy lifting.** The container has `scroll-snap-type: y mandatory`; each section has `scroll-snap-align: start` and `min-height: 100vh`. The browser handles the snap physics natively — no JS.
- **Snap is an opt-in mode.** The site supports two scroll modes: `snap` (mandatory snap, one section at a time) and `smooth` (free scroll). Mode is a site-setting flipped by the operator and applied as `[data-scroll-mode="snap"]` on the container.
- **Per-section entrance animations via IntersectionObserver.** Each section starts with `opacity: 0; transform: translateY(20px)` and a `.fade-in-view` marker class. `setupScrollAnimations()` observes them and toggles a `.visible` class when they enter the viewport — CSS handles the transition.
- **Gold-tinted dividers between sections.** Subtle gradient lines (`.section-divider`) give visual breathing room without breaking the snap rhythm.
- **First paint applies the mode immediately.** Server injects `data-scroll-mode` on `<html>` from site settings so the snap behavior is correct before JS loads.

## Data model
- `site_settings` row carries `scroll_mode` (`'snap'` or `'smooth'`). No per-section snap config.
- Section visibility/ordering comes from `page_sections` (see skill #1).

## API surface
- `GET /api/site-settings` — returns `scroll_mode` along with other site-wide config.
- `PATCH /admin/api/site-settings` — mode is toggleable from the admin Theme/Settings UI.

## Key files
- `public/styles.css` — `.landing-container[data-scroll-mode="snap"]` rules, `.snap-section` / `.landing-section` with `scroll-snap-align: start`, `.fade-in-view` / `.visible` transition classes, `.section-divider` gradient lines
- `public/script.js` — `applyScrollMode()` (~line 376) sets the data attribute from `siteSettings`; `setupScrollAnimations()` (~line 4700) creates the IntersectionObserver and toggles `.visible`
- `app.py` — server-side first-paint injection of `data-scroll-mode` and `data-density` attributes on `<html>` so first paint matches the active mode

## External dependencies
None — `IntersectionObserver` and `scroll-snap` are baseline in all evergreen browsers.

## Pitfalls
- **`mandatory` snap fights nested scrollers.** A scrollable container inside a snapped section can feel "stuck" because the parent keeps snapping back. Use `scroll-snap-stop: always` carefully, or switch to `proximity` snap for sections that contain long internal content.
- **Snap + anchor-link scrolling = jank.** `scrollIntoView({behavior:'smooth'})` on a snap container fights the snap engine. Either disable snap during programmatic scroll, then re-enable, or use `block: 'start'` and rely on snap to finish the alignment.
- **IntersectionObserver fires once per crossing.** If you want the fade to replay when scrolling back up, use `entry.isIntersecting` to add `.visible` AND remove it when leaving — but most landing pages prefer "fade in once, stay" for performance and reduced motion.
- **`min-height: 100vh` doesn't account for mobile browser chrome.** Use `100dvh` (dynamic viewport) where supported, or accept that the URL bar collapse leaves a thin strip.
- **Reduced-motion users need an opt-out.** Respect `prefers-reduced-motion: reduce` — skip the translate animation and just toggle opacity, or disable fades entirely.
- **Snap interferes with the fullscreen gallery** (skill #5) — when the gallery view is active, the landing container must be hidden or `overflow: hidden` so the gallery's own wheel handler isn't fighting the snap engine.

## Adaptation notes
- For horizontal landing pages, swap `scroll-snap-type: y` for `x` and `min-height: 100vh` for `min-width: 100vw`.
- To add per-section entrance variants (slide-up, slide-left, fade-only), use per-section data attributes (`data-anim="slide-up"`) and matching CSS rules — keep the observer logic unchanged.
- Pair with a fixed nav-dots column on the right that highlights the active section using the same IntersectionObserver entries.

## Adoption checklist
- [ ] `scroll-snap-type: y mandatory` on the landing container (gated by mode)
- [ ] `scroll-snap-align: start` + `min-height: 100vh` (prefer `100dvh`) on each section
- [ ] Site setting + admin toggle for `scroll_mode` (`snap` / `smooth`)
- [ ] Server-side first-paint injection of the mode attribute
- [ ] IntersectionObserver-driven `.visible` class for entrance fades
- [ ] `prefers-reduced-motion` opt-out
