---
name: Chat command routing — existing cards vs generated pages
description: Why visitor "show me X" requests should open real gallery cards via navigate, and how the page-build overview banner is rendered.
---

# Existing gallery cards vs. generatePage

When a visitor asks to SEE something that already exists as a gallery card, the
concierge should emit the `navigate` command (opens the real website gallery
card instantly via `goToSlide` + `showGallery` + side panel), NOT `generatePage`.

**Why:** `generatePage` builds a brand-new custom page from scratch — slow and
redundant when the content already exists as a curated gallery card. The model
used to default to `generatePage` for these, so visitors waited ~10s for a page
that just duplicated an existing card. This is steered purely in the system
prompt (the "SHOWING EXISTING GALLERY CARDS" rule), so if it regresses, check
that prompt block — there is no code-level router.

**How to apply:** `generatePage` is only for NEW custom content (comparisons,
custom layouts, summaries) the site does not already have.

# Page-build overview banner

The immersive page overlay (`#immersive-page-overlay`) is a sandboxed iframe
(`allow-scripts`, no `allow-same-origin`) — the parent CANNOT touch its DOM and
talks to it only via `postMessage`. Any build-time UI (the "Building" pulse, the
`.__streaming_overview__` banner) must be injected into the iframe's `srcdoc`
body at open time and removed inside the iframe's own `finish` message handler,
never from the parent. The overview text is the already-streamed reply preamble
(reply streams before the command JSON), escaped via `escapeHtml`, with a
hardcoded fallback string so a building+overview message is always shown even
when the model emits an empty pre-command reply.
