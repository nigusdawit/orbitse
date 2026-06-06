---
name: immersive "Building" overlay teardown invariant
description: why the visitor-chat page-builder can freeze on "Building", and the teardown rule that prevents it
---

# The immersive page-build "Building" overlay must be torn down on EVERY exit path

The visitor AI page builder (generatePage) opens a sandboxed iframe overlay the
INSTANT a `generatePage`/`generateHTML` action token is seen mid-stream. That
iframe shows a "Building" pulse that is removed **only** when the iframe
receives a `finish` postMessage. The success path (the generatePage command
handler) sends that `finish` (or one-shot re-renders). So the overlay's exit
depends on code that runs AFTER the streaming loop.

**The trap:** if the page-build overlay is open and the turn exits through any
path that does NOT reach the command handler, the pulse is never removed and the
visitor is stuck on "Building" forever. The known leak paths were:
- the outer `catch(error)` of the chat-stream function (network/reader/render
  exception thrown after the overlay opened) — it showed a "trouble connecting"
  message but did not close the overlay;
- the iframe-never-ready fallback timer, which only removed the message listener
  and left the overlay frozen.

**Why:** the server SSE side completes fine (it emits a valid command + done —
verify with a raw curl to /api/chat before assuming a backend hang). "Stuck on
Building" is almost always a frontend teardown gap, not a server hang.

**How to apply:** any new exit/error path in the chat-stream function must tear
down the immersive stream when one is in flight —
`closeImmersivePage(); resetImmersiveStreamState();` (both are no-ops when the
overlay isn't open, so calling them unconditionally is safe). Treat
"overlay opened during stream" as something that MUST be closed on success,
error, AND timeout.

## The deeper root cause: live chunk-streaming can never reveal the AI's pages

There is a SECOND, distinct "stuck on Building / blank page" failure that is NOT
a teardown gap. The AI's standard generatePage template hides every section with
`.animate-in{opacity:0}` and reveals them with a SINGLE inline `<script>` that
sets up an IntersectionObserver adding `.visible`. The page has no `forwards`
auto-play animations — visibility depends entirely on that script running.

The live-streaming renderer inserts HTML chunk-by-chunk via `insertAdjacentHTML`,
which does **not** execute `<script>`s. The "finish" handler re-runs them by
cloning, but by then the iframe's `DOMContentLoaded` has already fired — and AI
pages commonly gate setup on `DOMContentLoaded`, so the re-cloned script's
listener never fires. Result: all sections stay at `opacity:0` → a blank page
even though the HTML is fully present and the row is saved.

**The fix (current behavior):** the generatePage/generateHTML command handler
ALWAYS does an authoritative one-shot `openImmersivePage(cmd.html)` once the full
command arrives — it writes the COMPLETE document into the iframe via `srcdoc`, so
the browser parses it fresh and runs every `<script>` in normal load order
(`DOMContentLoaded` fires correctly) and all content reveals. The live "assembly"
stream is now purely a progress affordance; never trust it for the final result.
**Why:** correctness beats the streaming animation — the only cost is the CSS
intro replays once.

## Slowness ("long thinking") is generation time, not research rounds

For a full custom page, time-to-first-byte is ~0.5s and there is usually NO extra
tool/research round — the model goes straight to emitting the command. The ~20s
wait is the model writing the entire ~2KB HTML page in one round (gpt-4o-mini,
`max_tokens=16000`). Verify with a timed `curl -N` to /api/chat
(`-w "%{time_total} %{time_starttransfer}"`) before assuming a router/round bug.
