# Reading Progress Bar (Blog Scroll Indicator)

## When to use
You have long-form content pages (blog posts, knowledge-base articles, AI-generated long pages) where the visitor can't tell at a glance how much is left. A thin accent-colored bar pinned to the top of the viewport, growing from 0% to 100% as the visitor scrolls, gives instant feedback and measurably improves "read-to-end" rates.

## Architecture
A single fixed-position bar element rendered once per page:

```
<div class="reading-progress-bar" id="readingProgress"></div>
```

CSS pins it to the top of the viewport with `position: fixed; top: 0; left: 0; height: 3px; width: 0%`, painted in the theme accent token so it adopts the operator's brand without any JS knowledge of colors.

A passive `scroll` listener recomputes width on every scroll event:

```
progress = window.scrollY / (document.body.scrollHeight - window.innerHeight)
bar.style.width = clamp(progress, 0, 1) * 100 + "%"
```

`scrollHeight - innerHeight` is the "scrollable distance" — at the bottom of the page that ratio is exactly 1.0. Clamping to `[0, 1]` prevents overscroll on iOS Safari from pushing the bar past 100%.

The bar lives outside any flex/grid containers and uses `z-index` above the site nav but below modal overlays.

## Data model
None.

## API surface
None — pure DOM + CSS. The template includes the markup and an inline `<script>` that wires the scroll handler.

## Key files
- `templates/blog_post.html` (and any other long-form template) — the bar markup + the inline scroll handler.
- `public/styles.css` — `.reading-progress-bar` rule using `var(--color-accent)`.

## External deps
None.

## Pitfalls
- **Layout-shift on mount.** If you append the bar after page load, the first paint shows the page without it and "jumps" when it appears. Render it server-side in the template, hidden via `width: 0%`, so it's already in the DOM at first paint.
- **`scrollHeight` changes during page load** as images, fonts, and lazy-loaded sections come in. Recompute on `load`, on `resize`, AND on `scroll`, or the bar will report wrong percentages until everything settles. The cheapest fix: read `scrollHeight` fresh every scroll event — modern browsers cache it.
- **iOS bounce.** Overscroll at the top/bottom produces negative `scrollY` or `scrollY > maxScroll`. Always clamp.
- **High refresh-rate stutter.** A non-passive scroll listener throttles the browser's scroll thread. Always pass `{ passive: true }` to `addEventListener('scroll', ...)`.
- **`will-change: width`** sounds tempting but actively hurts here — width changes don't trigger compositing improvements and the hint forces a layer the GPU has to reblend on every frame.
- **Multiple long-form templates.** Don't copy-paste the script into each one; factor into a single `progress-bar.js` you include in any template that needs it. Otherwise the script will eventually drift between copies.

## Adaptation notes
- If you want a chapter indicator instead of a single bar, render N segments (one per `<h2>`) and fill them as each crosses the viewport top using `IntersectionObserver`.
- For RTL languages, flip the bar to fill right-to-left via `direction: rtl` on the container — no JS change needed.
- The same pattern works for any "how far through an experience" indicator: presentation slides (use slide index / total), onboarding flows (use step / total).
- Adding `prefers-reduced-motion: reduce` is a courtesy: disable the bar entirely (or freeze it at 100% once visited) for users who opted out of motion.

## Adoption checklist
- [ ] Add the `<div class="reading-progress-bar">` to every long-form template, server-rendered.
- [ ] Style it with `var(--color-accent)` so it inherits brand colors.
- [ ] Attach a passive scroll handler that recomputes width as `scrollY / (scrollHeight - innerHeight)`, clamped to `[0, 1]`.
- [ ] Recompute on `load` and `resize` too (or just always read fresh in the scroll handler).
- [ ] Verify on iOS Safari that overscroll doesn't push the bar past 100%.
- [ ] If used in multiple templates, factor the inline script into a shared JS file.
