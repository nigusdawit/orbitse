# Auto-Canvas Fallback for Long AI Replies

## When to use
The AI sometimes returns a 600-word answer with three lists and a table when the user just asked "tell me about your services." Cramming that into the corner chat bubble is unreadable; teaching the AI to *always* call a fancy `generatePage` action is unreliable (the model forgets, especially across providers and personas). The auto-canvas fallback is the safety net: when the agent returns long, structured text without an explicit visualization action, the chat *automatically* promotes it into a fullscreen frosted-glass canvas with proper typography, contextual eyebrow, accent-colored bullets, and styled tables.

## Architecture
After every agent message finishes streaming, the chat dispatcher checks three signals:

1. **Sentence count > 4** — counted by `/[.!?]\s/` splits (with the same abbreviation guards used by the sentence-by-sentence TTS streamer: Mr./Dr./e.g./etc.).
2. **Line count > 6** — `text.split("\n").length`.
3. **Structured markdown present** — any of: `#` heading line, two consecutive `- ` lines, a `|---|` table divider, or a ` ``` ` code fence.

If any signal trips AND the message has no explicit action tag (`generatePage`, `showSlide`, `playPresentation`), the dispatcher:

1. Builds an eyebrow label from the chat context — typically the first H1, or the first sentence-fragment matching the user's intent, or a static "Highlights".
2. Calls `openFullscreenCanvas({ eyebrow, html: renderMarkdown(text) })`.
3. Hides the long chat bubble behind a "View more" affordance so the chat dock doesn't double-render the same content.

The canvas itself is a separate full-screen overlay (NOT the same as the `generatePage` iframe — no sandbox, because the content came from the AI's prose path which has already been sanitized via DOMPurify). It uses these CSS regions:

- `.canvas-header` — gradient stripe with site brand and close button.
- `.canvas-eyebrow` — small accent-colored uppercase label.
- `.canvas-body` — the rendered markdown, styled with theme tokens.

Closing the canvas restores the chat dock and removes the "View more" affordance.

## Data model
None.

## API surface
- `openFullscreenCanvas({ eyebrow, html })` — opens the overlay with sanitized HTML.
- `closeFullscreenCanvas()` — restores the chat dock.
- `shouldAutoPromote(text) → boolean` — pure helper that runs the three signal checks.

## Key files
- `public/script.js` (or `chat-ui-kit/chat-ui.js`) — the dispatcher, `shouldAutoPromote`, `openFullscreenCanvas`, `closeFullscreenCanvas`.
- `public/styles.css` — `.fullscreen-canvas`, `.canvas-header`, `.canvas-eyebrow`, `.canvas-body` rules using theme tokens.

## External deps
None beyond the markdown renderer and DOMPurify (see siblings 03 and 04).

## Pitfalls
- **Trigger storm.** If the AI's response IS a `generatePage` JSON tag plus a 200-word fallback prose preamble, you'd both render the iframe AND promote the prose. The dispatcher must check for the explicit action FIRST and bail before running `shouldAutoPromote`.
- **Eyebrow extraction is hard.** Pulling the first H1 sounds clean but the AI often emits H1 last (a "Summary:" heading). Hand-tune: if the first 60 chars of the first paragraph make a decent label, use that; otherwise fall back to a static word.
- **"View more" must persist after the canvas closes.** A visitor who closes the canvas and scrolls back through chat history expects to re-open it. Don't garbage-collect the affordance.
- **Mobile fullscreen + browser chrome.** Use `100dvh` and `env(safe-area-inset-bottom)` to keep the close button reachable on iOS.
- **Don't auto-promote tool-call summaries.** When the AI message is just `Searched the knowledge base for "X"`, the structured-markdown heuristic shouldn't fire — keep those in the chat dock.
- **Sentence-split abbreviations.** Without the abbreviation guard list, `Dr. Smith says...` reads as two sentences and you'll wrongly count it as "long enough to promote".

## Adaptation notes
- The three thresholds are tuning knobs; raise them if your users prefer chat-first, lower them if they prefer canvas-first. Consider making them a per-tenant setting.
- The canvas can host non-markdown surfaces too — a generated table, a chart, an image grid — by exposing additional `openFullscreenCanvas({ kind, props })` shapes.
- For the very first AI reply of a conversation, auto-promote more eagerly (e.g. drop the "no explicit action" requirement) to establish the canvas affordance early in the visitor's mental model.
- A "Pin to canvas" pin icon on each chat bubble lets power-users promote on demand, even when the heuristic didn't fire.

## Adoption checklist
- [ ] Implement `shouldAutoPromote(text)` with the three signals.
- [ ] Wire the dispatcher: explicit action → handle it; long-and-structured → `openFullscreenCanvas`; else → chat bubble.
- [ ] Build the `.fullscreen-canvas` overlay with `.canvas-header` / `.canvas-eyebrow` / `.canvas-body` regions, styled with theme tokens.
- [ ] Hide the source bubble behind a re-openable "View more" affordance.
- [ ] Use `100dvh` + safe-area insets for mobile.
- [ ] Make the abbreviation-guarded sentence counter shared with the TTS sentence streamer.
- [ ] Verify tool-call summary messages don't promote.
