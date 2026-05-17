# Three.js Sphere View (Section Carousel + Classic Image Sphere)

## When to use
You want a single immersive 3D "wow" entry point on the landing page that doubles as navigation — without bringing in a game engine or React Three Fiber. Two visual modes ship out of the box: a ring of glassmorphic HTML cards orbiting in 3D (each card linking to a real site section), or a rotating sphere of photos with a particle field. Admin picks the mode; the viewer drags to rotate and scrolls to zoom.

## Architecture
A fullscreen overlay is mounted lazily on first click of the "Sphere View" button. Two scenes are co-rendered into the same canvas stack:

- **WebGL `THREE.Scene`** (`WebGLRenderer`) — particle field background (`PointsMaterial` on a `SphereGeometry` of randomized points). Also draws the orbiting image planes when the active mode is "classic".
- **CSS3D `THREE.Scene`** (`CSS3DRenderer`) — when mode is "section_carousel", each site section becomes a `CSS3DObject` wrapping a real `<div class="sphere-section-card">`. Because cards are real DOM, native CSS, fonts, theme tokens, hover states, and click handlers all work — no canvas text-rendering hacks.

Both renderers share the same `THREE.PerspectiveCamera` and the same parent `THREE.Group` rotation, so dragging rotates particles and cards together and they stay perfectly aligned. The CSS3D renderer's element is positioned `absolute; inset: 0; pointer-events: none` on the container, with `pointer-events: auto` re-enabled only on the cards — so drag-to-rotate is captured by the WebGL canvas beneath.

Animation is driven by a single `requestAnimationFrame` loop that:
1. Lerps `currentZoom → targetZoom` (set by the wheel listener).
2. Lerps `currentRotation → targetRotation` (set by drag, plus an auto-rotate increment when not dragging).
3. Calls `webglRenderer.render(...)` and `css3dRenderer.render(...)`.

Card-mode layout: N cards are placed around a horizontal ring using `(cos θ, 0, sin θ) * radius`, where `radius = card_count * card_gap / (2π)`. Each card is rotated to face the center via `lookAt(scene.position)`.

## Data model
`sphere_settings` — singleton config row, edited from admin Sphere View tab. Key columns:
- `enabled BOOLEAN` — show the entry button at all.
- `view_mode TEXT` — `'section_carousel'` or `'classic'`.
- `heading TEXT`, `subheading TEXT` — title shown above the 3D area.
- `rotation_speed REAL` — radians per frame auto-rotate.
- `particle_count INT`, `particle_opacity REAL` — WebGL particle field density.
- `sphere_radius REAL`, `position_randomness REAL` — classic-mode image placement.
- `image_size REAL`, `zoom_min REAL`, `zoom_max REAL`.
- `card_scale REAL`, `card_gap REAL` — section-carousel layout knobs.
- `image_source TEXT` — `'gallery'` | `'uploads'` | `'custom'` (classic mode image pool).

`sphere_images` — only used by classic mode when `image_source='custom'`: one row per image URL, ordered.

## API surface
- `GET /api/sphere-settings` — public read, returns the singleton + (for classic mode) the image list. Cacheable like every other public read endpoint.
- `GET /admin/api/sphere-settings`, `PUT /admin/api/sphere-settings` — admin read/write.
- `GET/POST/PUT/DELETE /admin/api/sphere-images` — only relevant in custom-image mode.

JS entry points (in `public/script.js`):
- `initSphereButton()` — wires the button visibility off `sphere_settings.enabled`.
- `createSphereScene(settings)` — builds the classic WebGL sphere.
- `createSectionsScene(settings)` — builds the CSS3D card carousel.

## Key files
- `public/script.js` — both scene builders, the unified animation loop, drag/wheel handlers.
- `public/styles.css` — `.sphere-section-card`, fullscreen overlay container, particle canvas layering.
- `app.py` — `sphere_settings` table init + the four CRUD routes above.
- `templates/admin/dashboard.html` — "Sphere View" tab with mode picker and live-preview iframe.

## External deps
- Three.js core (`THREE`) — CDN script tag in `index.html`.
- `THREE.CSS3DRenderer` — separate addon script, loaded only when the sphere button is enabled.
- No bundler. Both globals attached to `window`.

## Pitfalls
- **Two renderers, two canvases.** Forgetting to set `pointer-events: none` on the CSS3D layer breaks drag-to-rotate on the WebGL layer — and the bug only shows up when you click empty space between cards.
- **HTML cards do NOT receive theme-token live updates** the way native HTML does, because the CSS3DRenderer wraps them in a `transform: matrix3d(...)` element that breaks `position:fixed` and some `vh` units. Use CSS variables everywhere inside the card.
- **Particle count is not free.** Above ~5000 particles, low-end laptops drop to <30fps. Cap admin input.
- **Resize is non-trivial.** Both renderers + the camera aspect must update on `window.resize`, and CSS3D needs `setSize(w, h)` AND a re-style of the container.
- **Auto-rotate fights drag.** Pause auto-rotate while `isDragging===true`, resume on mouseup with a short fade-in or rotation jumps.
- **First click latency.** Three.js + CSS3DRenderer is ~150KB gzip; load it lazily after the landing page is interactive, not in the initial bundle.

## Adaptation notes
- For a single-mode build, delete the unused scene builder entirely — the only shared code is the `requestAnimationFrame` driver and the drag/zoom handlers.
- The card list is currently sourced from `page_sections` (so admin section ordering drives the ring). To use a different data source, swap the slice that builds the `cards = [...]` array.
- For VR/AR, drop CSS3DRenderer and recreate cards as WebGL textured planes — but you lose theme-token responsiveness.
- Auto-rotate can be replaced with scroll-linked rotation (`window.scrollY → group.rotation.y`) for a "parallax sphere on scroll" effect.

## Adoption checklist
- [ ] Load Three.js + CSS3DRenderer addon via CDN, lazily.
- [ ] Create the `sphere_settings` table (+ `sphere_images` only if classic mode is wanted).
- [ ] Build the admin tab with the knobs listed under Data model.
- [ ] Implement `createSphereScene` (classic) and/or `createSectionsScene` (cards).
- [ ] Mount both renderers into the same overlay container; layer CSS3D above WebGL with `pointer-events: none`.
- [ ] Add drag + wheel handlers that update `targetRotation` and `targetZoom`; lerp in the RAF loop.
- [ ] Wire window-resize handler that updates BOTH renderers + camera.
- [ ] Cap particle count input in admin.
