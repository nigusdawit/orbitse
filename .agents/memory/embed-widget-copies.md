---
name: Embed widget — which copy is live
description: The embeddable chat widget exists as two copies; only one is actually served by the running app.
---

# Embed widget: live copy vs. mirror, and the Shadow-DOM overlay trap

The embeddable concierge widget ships as **two byte-identical copies**:

- `embed/widget/chat-ui.js|css|voice.js` — **the LIVE copy**. The running
  `main:app` (app.py) serves these: `/widget/<file>` → `embed/widget/`, and
  `/embed/loader.js` → `embed/loader.js`.
- `admin_ai_platform/web/chat-ui.js|css|voice.js` — a mirror for the standalone
  `admin_ai_platform` `create_app()` platform, which is **NOT the running app**.

**Why this matters:** editing only `admin_ai_platform/web/*` changes nothing on
the live site. Always edit `embed/widget/*` (and keep the mirror in sync).

**How to apply:** when changing the widget, edit both copies and verify they're
identical (`diff -q`). Nothing enforces parity yet (a guard test is a known
follow-up).

## Shadow-DOM overlay trap
`embed/loader.js` mounts the widget in a **Shadow DOM** and injects
`/widget/chat-ui.css` *into the shadow root*. Anything appended to
`document.body` (outside the shadow) renders **unstyled** on third-party hosts.
The fullscreen rich-response/gallery overlay must be appended to the shadow
mount (`S.mount`), not `document.body`. The loader host is
`position:fixed; width:0; height:0` with **no** transform/filter, so a child
`position:fixed; inset:0` overlay stays viewport-fullscreen inside the shadow.

## Cross-origin theming
The widget brand-matches the site by fetching the public `/api/theme` feed
(palette + fonts). For that to work cross-origin it must be listed in
`_EMBEDDABLE_PREFIXES` in app.py (gives embed-key auth + scoped CORS). The host
page has none of the site's CSS theme vars, so read theme from `/api/theme`, not
from `getComputedStyle(documentElement)`.
