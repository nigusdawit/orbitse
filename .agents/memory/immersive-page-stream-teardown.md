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
