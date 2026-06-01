---
name: Streaming AI page-build infra (gunicorn + token cap)
description: Why on-demand AI page builds froze on "Building", and the infra constraints that keep streaming endpoints alive.
---

# Streaming AI page-build ("generatePage") reliability

The concierge's on-demand page builder streams a full HTML page over SSE to the
browser, which live-renders it into a sandboxed iframe and shows a "Building"
pulse until a complete `generatePage`/`generateHTML` command arrives. Three
independent things can make it freeze on "Building" forever:

1. **Gunicorn worker timeout kills long streams.** A default `sync` worker with
   the default `--timeout 30` will be SIGKILLed mid-stream on any AI generation
   longer than 30s (look for `[CRITICAL] WORKER TIMEOUT` in the workflow log).
   **Streaming/SSE endpoints REQUIRE a long timeout and a non-sync worker.**
   Use `--worker-class gthread --threads N --timeout 300` in BOTH the dev
   workflow command and the deploy/prod config. gthread is safe here because DB
   access goes through a thread-safe `ThreadedConnectionPool` (keep pool max ≥
   thread count) and boot is idempotent.
   **Why:** the single biggest cause of "stuck on Building" was the worker being
   killed, not a model or frontend bug.

2. **Per-round `max_tokens` too small truncates the page.** The visitor chat
   round must allow enough output tokens to emit a whole HTML page inside one
   command JSON; a small cap (e.g. 4096) cuts the JSON off unclosed/unparseable
   so the command never completes and the pulse never clears. Keep the visitor
   round cap large (~16000, safe for gpt-4o family's 16384 and Claude).

3. **Frontend teardown race.** The interrupted-build safety net must finalize
   the iframe stream in an acknowledgment-aware way: the iframe sends a `ready`
   handshake before queued messages (including `finish`, which removes the
   pulse) can be delivered. Tearing down (removing the message listener) before
   `ready` arrives strands the `finish` and the pulse never clears. Defer the
   reset until `ready` drains the queue, with a timeout fallback so the listener
   is never leaked.

## Model choice for streaming page builds
Claude Sonnet 4.5 gives the best design quality but streams page builds very
slowly in this environment (minutes per page) — bad UX for a waiting visitor.
gpt-4o-mini completes a full page in ~15-20s. The active provider/model lives in
the `agent_provider_settings` singleton (id=1) and is editable from the admin
"AI Provider" tab (`/admin/api/llm-provider` GET/PUT), super-admin / `llm_provider`
feature gated.

## Harmless log noise
A flood of `[INFO] Handling signal: winch` in the gunicorn log is just the
Replit console pane sending SIGWINCH (terminal resize). Gunicorn logs each one
but takes no action while serving — it does NOT indicate a crash or restart.

## Front-end JS changes don't reach the browser until TWO things happen
The public homepage loads `script.js`+`voice.js` as ONE minified, content-
fingerprinted bundle (`asset_bundle.py`, served at `/bundle.<sha256[:12]>.min.js`),
**built once per gunicorn worker and cached in-memory for the worker's lifetime**.
Editing `script.js` alone changes NOTHING the visitor sees until:

1. **The worker restarts** so `asset_bundle.build_bundle()` re-reads the sources
   and computes a new hash. `gunicorn --reload` only watches *Python* files, not
   static JS — so a JS-only edit needs a manual workflow restart.
2. **The index HTML is fetched fresh** so the browser gets the new bundle URL.
   `serve_index` must send `Cache-Control: no-cache, no-store, must-revalidate`
   on the HTML; otherwise the browser/preview keeps serving cached HTML with the
   OLD bundle URL and the new code never loads (the bundle URL itself stays
   forever-cacheable because it's hash-fingerprinted — only the HTML must
   revalidate).

**Why:** multiple rounds of "my front-end fix didn't change anything" were caused
by the stale cached bundle, NOT by the JS logic. After any front-end edit:
restart the workflow, then confirm with `curl -sD- .../ | grep cache-control`
and `curl -s .../ | grep -o '/bundle\.[a-f0-9]\{12\}\.min\.js'`.

## Immersive page render: prefer a one-shot fallback over trusting the stream
The live progressive iframe render depends on a cross-iframe postMessage `ready`
handshake that is unreliable in the preview environment. The `generatePage`
command handler tracks `_immersiveStream.ready/completed/written` and only trusts
the streamed page when `ready && completed && written>0`; otherwise it falls back
to `openImmersivePage(cmd.html)` (a fresh `srcdoc` write, which always works since
the "Building" pulse itself renders via `srcdoc`). Open the "Building" overlay as
soon as the `{"action":"generatePage|generateHTML"}` token is seen — don't wait
for the `html` field — so it appears promptly instead of after the text preamble.
