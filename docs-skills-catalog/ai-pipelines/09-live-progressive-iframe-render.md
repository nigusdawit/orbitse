# Live Progressive Iframe Page Render

**Category:** AI / LLM Pipelines

## When to use
The AI streams a structured command like `{"action":"generatePage",
"html":"<style>..."}` and you want the visitor to watch the page
build in real time inside a sandboxed iframe, instead of waiting for
the full JSON to arrive and the page to pop in at the end.

## Architecture
- **Detector:** while accumulating SSE tokens into a buffer, regex-
  match `\{"action"\s*:\s*"(generatePage|generateHTML)"` and
  `"html"\s*:\s*"` to detect the start of a renderable command.
  Open the iframe overlay the moment both match.
- **Decoder:** call `extractStreamingJsonString(buffer, "html")`
  (see skill 02) every chunk to get the in-progress decoded HTML.
- **Boundary flush:** maintain a `pageStreamWritten` cursor. Compute
  `safeEnd = findTopLevelHtmlBoundary(decoded, written)` — the last
  position where every opened element has been closed. Only flush
  `decoded.substring(written, safeEnd)` so chunks always parse as
  complete elements.
- **Iframe sandbox:** the iframe has `sandbox="allow-scripts"` and a
  `srcdoc` that includes a tiny shim: a `<div id="__stream_root__">`
  mount node and a `message` listener that calls
  `root.insertAdjacentHTML('beforeend', e.data.chunk)` for every
  posted chunk. The parent uses `iframe.contentWindow.postMessage`
  to deliver chunks — direct DOM access is blocked by the sandbox,
  so postMessage is the only safe channel.
- **Theme injection:** the iframe's srcdoc auto-injects the site's
  CSS custom properties (`--color-accent`, `--font-serif`,
  `--hero-image`, etc.) into `:root` so the generated page visually
  flows from the live site.
- **End-of-stream:** when the SSE closes, the standard `case
  'generatePage'` branch DETECTS the live render already happened
  (via a flag like `pageStreamStarted`) and SKIPS the one-shot
  re-render, so animations the visitor just watched don't restart.
- **Error path:** if the stream errors mid-render, tear down the
  overlay and reset the live-render state so a half-built page
  doesn't stick around.

## Data model
None — purely client-side ephemeral state.

## API surface
- Consumer of any SSE chat endpoint that may emit `generatePage` /
  `generateHTML` JSON commands.

## Key files
- `public/script.js` — detector + flush loop in `chatSendStreaming`
  (~line 6260 onward), `openImmersivePageStreaming` /
  `appendImmersivePageStreaming` / `resetImmersiveStreamState`,
  `findTopLevelHtmlBoundary`, `extractStreamingJsonString` (~line 9266),
  iframe srcdoc shim (~line 8912).

## External deps
None.

## Pitfalls
- Flushing mid-element dumps raw CSS/markup as visible text on the
  next chunk — always wait for a top-level boundary.
- Without `sandbox="allow-scripts"` the generated page can access
  the parent — DON'T loosen the sandbox.
- Without `allow-scripts` the iframe's message listener can't run —
  it MUST be `allow-scripts` (omit `allow-same-origin` to keep the
  iframe origin-isolated).
- The one-shot final renderer must check the live-render flag, or
  the visitor sees the page rebuild from scratch when the SSE closes.
- A new chat message arriving mid-render: close the overlay first
  (or queue), don't append into the previous render.
- Long Unicode characters split across SSE byte chunks need a
  `TextDecoder({stream:true})` upstream of the JSON-string decoder.

## Adaptation notes
- Generalizes to any progressive structured output: streaming
  Markdown, streaming SVG, streaming Mermaid diagrams. Swap the
  boundary detector for the format you're rendering.
- For React/Vue consumers, instead of `insertAdjacentHTML` into a
  sandbox, mount a controlled component and feed it the decoded
  string as state — but you lose the security guarantees of the
  sandbox and inherit XSS responsibility yourself.

## Related skills
- `02-partial-json-streaming-decoder.md` — the decoder this skill
  relies on.
- `01-streaming-tool-call-loop.md` — the SSE this consumes.
- `03-live-editable-system-prompts.md` — the prompt teaches the AI
  to emit `generatePage` rather than long prose for visual answers.
