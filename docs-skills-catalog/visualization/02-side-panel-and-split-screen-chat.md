# Side-Panel AI Chat & Split-Screen Page Overlay

## When to use
Your AI agent has actions that take over the screen (navigate the visitor to a gallery slide, render a generated page, play a presentation). The chat bubble can't keep dominating the corner during those moments — but you also can't make the visitor scroll back to the chat to reply. You want the chat to morph into a frosted-glass companion panel that stays visible alongside the content, then snap back to its normal corner placement when the takeover ends.

## Architecture
Two body-level CSS classes act as global mode switches; toggling them re-flows the existing chat DOM (no clone, no portal):

- `body.side-panel-active` — entered when the AI emits `showSlide` (gallery slide navigation). The chat dock collapses to a tall frosted strip pinned to the right edge of the viewport. The "live" agent bubble shows only the latest message; older turns are tucked behind a toggleable history accordion (`#side-panel-history`).
- `body.split-screen-active` — entered when the AI emits `generatePage`. The screen splits: chat takes the left third, a sandboxed `<iframe>` mounts the streamed HTML in the right two-thirds (see `ai-pipelines/09-live-progressive-iframe-render.md` for the iframe streaming protocol).

Both modes are exited automatically when the chat closes, when the user hits Escape, or when the next agent message lacks a takeover action.

On mobile, `side-panel-active` is restyled via media query to a fixed-height bottom strip (e.g. 120px) — the latest agent message shows inline; tapping it expands the full history sheet upward over the page content.

The same chat composer DOM is reused in every mode. Only the **container** moves visually (via CSS positioning rules keyed off the body class) — input focus, scroll state, message refs, and the streaming render loop are never re-mounted, so a half-typed message survives the mode switch.

## Data model
None. The body-class mode is pure UI state held in JavaScript memory; no DB or session columns.

## API surface
Frontend module API:
- `chatUI.enterSidePanel({ latestMessageHTML })` — apply body class, render the single visible bubble.
- `chatUI.enterSplitScreen({ iframeMountId })` — apply body class, return the mount node for the streaming iframe.
- `chatUI.exit()` — remove both body classes, restore default chat dock.

The takeover is triggered by the streaming action dispatcher when it sees `{"action":"showSlide", "slug":"…"}` or `{"action":"generatePage", "html":"…"}` in the AI's JSON-tagged response stream.

## Key files
- `public/script.js` (and the optional `chat-ui-kit/chat-ui.js` extraction) — the dispatcher and `enterSidePanel`/`enterSplitScreen`/`exit` functions.
- `public/styles.css` — `body.side-panel-active`, `body.split-screen-active`, `.side-panel-hidden`, `.split-slide`, mobile media queries.
- `public/index.html` — the chat DOM that gets re-styled (NOT cloned) by these modes; the `#split-screen-content` mount node for the iframe.

## External deps
None. Pure CSS class toggles + existing chat DOM.

## Pitfalls
- **Don't re-mount the chat list.** If you do, you'll lose scroll position, in-flight streaming bubbles, and the typing indicator. Use CSS to reposition.
- **iOS viewport unit math is wrong** for `100vh` when the URL bar is showing. Use `100dvh` for the side-panel and split-screen containers, or you'll see content cropped at the bottom.
- **Action keying.** The AI may emit `showSlide` and `generatePage` in the same turn (it shouldn't, but the model is stochastic). Decide a deterministic priority — current code prefers `generatePage` because it's the bigger takeover.
- **Mobile bottom strip vs. mobile keyboard.** When the visitor focuses the chat input, the keyboard pushes the strip up. Use `<meta name="viewport" content="...interactive-widget=resizes-content">` (already set in `dashboard.html`) so the layout reflows instead of the strip floating over the keyboard.
- **Escape-to-exit must not also close the chat** — bind it on the body in the active mode, prevent default, and only call `exit()`.

## Adaptation notes
- A third mode (e.g. `body.video-active` for a fullscreen video call surface) is one additional CSS class away — the dispatcher is just a switch.
- The split-screen ratio (currently ~33/67) is a CSS variable; admins could expose it as a theme knob.
- If you don't ship a sandboxed page generator, you can ship `side-panel-active` alone — they're independent.

## Adoption checklist
- [ ] Add two body classes to your stylesheet: one repositions the chat to a right strip, one repositions it to a left third + reserves the rest for an iframe.
- [ ] Add a `.side-panel-history` accordion that hides all but the latest agent bubble by default.
- [ ] Add a mobile media query that flips the right strip to a bottom strip.
- [ ] In the streaming action dispatcher, call `enterSidePanel` / `enterSplitScreen` when those actions appear, and `exit()` on chat-close / Escape / agent message without an action.
- [ ] Use `100dvh` (not `100vh`) for all takeover containers.
- [ ] Verify input focus and scroll survive a mode switch.
