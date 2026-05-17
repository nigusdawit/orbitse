# Client-Side Partial-JSON Streaming Decoder

**Category:** AI / LLM Pipelines

## When to use
The AI streams a single JSON command (e.g. `{"action":"generatePage",
"html":"<style>..."}`) and you want to start using the value of a
specific string field BEFORE the JSON object is complete — so the UI
can render progressively instead of waiting for the closing brace.

## Architecture
A pure function `extractStreamingJsonString(buffer, key)` that:
1. Locates `"<key>"\s*:\s*"` in the buffer.
2. Walks character-by-character from that point, decoding JSON string
   escapes (`\n \t \r \" \\ \/ \b \f \uXXXX`) as it goes.
3. Returns `{value, complete}` — `complete=true` only when an
   unescaped closing `"` is found.
4. Bails with `complete=false` (and the value-so-far) the moment it
   hits an incomplete escape — never decodes a half escape, so the
   next call resumes safely after more bytes arrive.

The caller keeps a `written` cursor and only flushes the delta
`value.substring(written, safeEnd)`. For HTML targets, define
`safeEnd` as the last position where every opened tag is closed
(`findTopLevelHtmlBoundary`) so chunks always parse as complete
elements when re-injected via `insertAdjacentHTML`.

## Data model
None. Pure client-side state: `{buffer, written, complete}`.

## API surface
None — function operating on the SSE buffer the chat client already
maintains.

## Key files
- `public/script.js` — `extractStreamingJsonString` (~line 9266) and
  `findTopLevelHtmlBoundary` used by the live-page renderer.

## External deps
None.

## Pitfalls
- The naive approach (`JSON.parse` on the partial buffer) throws on
  every chunk until the very end — defeats the streaming goal.
- Flushing HTML mid-element (inside an open `<style>` or `<div>`)
  causes the next chunk to render as visible text instead of CSS or
  markup. Always flush at top-level element boundaries.
- `\u` escapes need 4 hex digits — if fewer than 4 bytes remain in
  the buffer, return incomplete; don't guess.
- Unicode characters that arrive split across TCP chunks: use
  `TextDecoder({stream:true})` on the byte stream BEFORE feeding
  characters to this decoder.

## Adaptation notes
- Works with any LLM that streams plain text tokens (Anthropic,
  OpenAI, local models). The function never assumes a provider —
  only that bytes accumulate.
- For non-HTML targets (Markdown, plain text), drop the boundary
  detector and flush whatever the decoder returns.

## Related skills
- `01-streaming-tool-call-loop.md` — the server side that produces
  the token stream this decoder consumes.
- `09-live-progressive-iframe-render.md` — the canonical consumer
  for `key="html"` deltas.
