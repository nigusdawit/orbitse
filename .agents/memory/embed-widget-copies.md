---
name: Embed widget — iframe of the real homepage + band sizing
description: The live embeddable concierge is an iframe of the REAL homepage in widget mode, not a Shadow-DOM copy; sizing it has a vh deadlock trap.
---

# Embed widget: how it's actually mounted, and the iframe band-sizing trap

The live embeddable concierge is the **REAL homepage** loaded in a cross-origin
`<iframe>` in "widget mode" (`html.aap-widget`, set by an early inline script in
`public/index.html` keyed on the `/embed/concierge` path). `embed/loader.js`
mounts that iframe on the host page; `public/widget-bridge.js` runs inside it.
This gives byte-for-byte parity (chat, voice, generatePage, canvas) and perfect
style isolation — there is **no reimplementation** to keep in sync.

**Why:** an earlier design used a Shadow-DOM copy under `embed/widget/*` (+ an
`admin_ai_platform/web/*` mirror). That copy is **legacy / not served** for the
concierge embed now — don't chase the "two copies" / Shadow-DOM overlay trap for
the live widget; edit the homepage + its CSS/JS instead.

## The iframe band-sizing deadlock (the big trap)
The loader sizes the iframe to a **bottom band** so the host page stays
clickable above it, and the bridge reports the needed band height. Inside the
iframe, `window.innerHeight` / `vh` **IS that band** — i.e. the thing we're
trying to compute. So anything that sizes off the iframe's own viewport
self-references and deadlocks at a too-small size:
- a CSS panel cap like `max-height: 70vh` → small band → small 70vh → small
  panel → small band; the panel renders clipped to a sliver.
- the bridge capping its reported band at `window.innerHeight` → pins the band to
  its current height so a taller surface (the expanded chat panel) can never
  grow into view.

**How to apply:** size off the **HOST** viewport, not the iframe's. `loader.js`
posts the host `window.innerHeight` to the iframe (`{__aap:"aap-host",
type:"hostsize", vh}`, scoped to the concierge origin); the bridge stores it in
`--aap-host-vh` and uses it (not iframe vh) to cap the band; widget-mode CSS
sizes `#chatbot-panel` off `--aap-host-vh`. The loader also caps the iframe at
the host height as a backstop. Bridge trusts only `ev.source === window.parent`.

## Modal vs. band
Only truly page-covering surfaces (`#split-overlay`, `#immersive-page-overlay`)
go fullscreen (bridge `isModal()`). The expanded chat panel is just a
bottom-anchored card — it's a `FLOAT_IDS` member measured into the band so the
host stays clickable, exactly like the main site.

## Widget-mode surfaces need an explicit dark backdrop
In widget mode the page is transparent (floats over the host). The frosted-glass
concierge surfaces (`#chatbot-bar`, `#chatbot-panel`, `#side-chat-panel`) are
designed to sit over the site's own dark bg, so over a **light** host they read
faint/unreadable unless given an opaque dark backdrop derived from the theme
base color. **Gotcha:** the proactive welcome card is `#chatbot-panel` (not
`#side-chat-panel`) — the dark rule must cover all three surfaces.

## Clip-path tightly clips the iframe → kills shadows, chases animations
`loader.js` applies a `clip-path` that hugs each visible surface's rect (the
bridge reports `surfaceRects`) so the transparent gaps pass clicks to the host.
Two visual gotchas fall out of that, both fixed in the `html.aap-widget` CSS
block:
- a surface's `box-shadow` gets **hard-cut** by the clip into an ugly grey
  rectangle ("shade"). Kill `box-shadow` on every widget floating surface
  (`#chatbot-panel`, `#side-chat-panel`, `.voice-intro-card`,
  `.page-archive-bubble`/`-btn`, `.page-archive-popover`) — not just the pill.
- if a surface slides/fades open over several frames, the clip **chases** it
  frame-by-frame → flicker. Set `transition:none` on those same surfaces
  (keyframe `animation` like the typing dots is left intact) and remove the
  iframe's own `height` transition in `loader.js` so the box + clip change in one
  step. **Why:** the clip update is instant; anything animated lags it.

## Cache-busting
`public/styles.css` is referenced with `?v=_STYLES_CSS_VERSION` (regex-injected
in `app.py`) — bump it on visible CSS changes. `/embed/concierge`,
`/widget-bridge.js`, and `/embed/loader.js` are served `no-cache`, so JS edits
reach embeds without a version bump.
