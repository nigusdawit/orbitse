# Immersive Fullscreen Gallery (Swipe / Wheel / Keyboard Navigation)

**Category:** Content Management
**Related:** `content/06-snap-scroll-landing.md`, `content/07-glassmorphic-design-system.md`

## When to use
You want a fullscreen, magazine-style image gallery (one slide at a time, edge-to-edge background image, overlay text) navigable by mouse wheel, touch swipe, arrow keys, and on-screen arrows. Suitable for hero galleries, portfolio walkthroughs, room/property tours, product showcases.

## Architecture
- **All slides are pre-rendered in the DOM** with absolute positioning and stacked z-index. Navigation toggles three classes — `.slide-active`, `.slide-prev`, `.slide-next` — and CSS transitions animate between them. No re-render on each navigation.
- **One active slide at a time.** Previous/next slides are kept in DOM but translated off-screen + opacity 0 so transitions look continuous in both directions.
- **Scroll cooldown gates input.** A constant (`SCROLL_COOLDOWN_MS = 350`) blocks repeat wheel/swipe events so a single trackpad flick navigates exactly one slide instead of skipping six. CSS `--slide-transition` is aligned with the same value to prevent mid-animation flicker.
- **Three input handlers, one navigate function.** `handleWheel`, `handleTouchStart`/`End`, and key listeners all dispatch to `navigateSlide(direction)`. Centralizes the cooldown check + edge detection.
- **Slide content overlay is separate from background.** Background is `.gallery-slide-bg` (image or video, Ken Burns animation); foreground is `.gallery-slide-content` (title, subtitle, CTA) overlaid with a vignette gradient for readability.

## Data model
Driven by the existing `gallery_cards` table (one row per slide). No gallery-specific state in the DB — current slide index lives in JS only.

| Column (typical) | Notes |
|---|---|
| `id` SERIAL PK | |
| `title`, `subtitle`, `description` | Overlay text |
| `image_url` / `video_url` | Slide background |
| `cta_text`, `cta_url` | Optional in-slide call to action |
| `sort_order` | Drag-reorderable (see skill #3) |
| `enabled` | Hide without delete |

## API surface
- `GET /api/gallery-cards` — public list, enabled only, ordered by `sort_order`.
- Admin CRUD via `/admin/api/gallery-cards/...` (standard pattern).

No gallery-specific endpoint — navigation is 100% client-side state.

## Key files
- `public/script.js` — `navigateSlide(direction)`, `handleWheel`, `handleTouchStart`/`End`, key listener, `SCROLL_COOLDOWN_MS = 350` constant (gallery navigation section, ~line 4310)
- `public/styles.css` — §10–12 (~lines 2800–3200): `.gallery-view`, `.gallery-slide`, `.slide-active`, `.slide-prev`, `.slide-next`, navigation dots, counter, arrows
- `public/index.html` — `.gallery-view` container with empty `<div>` populated client-side from `/api/gallery-cards`

## External dependencies
None. Pure CSS transitions + vanilla JS event handlers.

## Pitfalls
- **Trackpad inertia floods wheel events.** Without the cooldown, a single flick fires 30+ wheel events and skips multiple slides. The cooldown value must match CSS transition duration or the animation looks janky.
- **Touch swipe needs a distance + direction threshold.** Otherwise tapping a CTA accidentally registers as a swipe. ~50px horizontal threshold with vertical-cap (ignore if vertical movement > horizontal) works well.
- **Preload only adjacent slides.** Eagerly loading 30 hero images on first paint kills initial-load metrics. Use `loading="lazy"` on non-adjacent slides, or preload only `current ± 1`.
- **Keyboard nav must respect focus context.** Arrow keys inside a text input should NOT navigate slides. Check `document.activeElement.tagName` before handling.
- **`scroll-snap` containers conflict with wheel handlers.** If the gallery lives inside a snap-scroll landing page, the gallery view must `overflow: hidden` and `preventDefault` on wheel events, or both the snap container AND the gallery try to scroll.
- **Video backgrounds need a poster image.** Without it, mobile browsers show a black flash before the video first-frames in.

## Adaptation notes
- For accessibility, add `aria-roledescription="slide"` on each slide, `aria-current="true"` on the active one, and an off-screen live region announcing "Slide N of M" on navigation.
- To add slide-specific layouts (text-left, text-center, text-right), use a per-row `layout` enum + CSS classes — keep the navigation engine unchanged.
- For very large galleries (>50 slides), virtualize: render only `current ± 2` slides and recycle nodes. Below 50, full DOM render is simpler and performs fine.
- Replace the click-to-zoom feature with a fullscreen lightbox (`requestFullscreen()` on the slide element).

## Adoption checklist
- [ ] All slides pre-rendered, navigation via class swap (`.slide-active` / `-prev` / `-next`)
- [ ] One `navigateSlide(direction)` function called by all input handlers
- [ ] `SCROLL_COOLDOWN_MS` constant matched to CSS transition duration
- [ ] Touch swipe with horizontal distance threshold + vertical-cap
- [ ] Keyboard handler that ignores input-focused contexts
- [ ] Lazy load for non-adjacent slide images
