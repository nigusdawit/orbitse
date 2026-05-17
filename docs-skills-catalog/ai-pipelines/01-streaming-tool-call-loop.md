# Streaming Tool-Call Loop

**Category:** AI / LLM Pipelines

## When to use
You need a server-streamed chat endpoint where the LLM can also call
function tools (lookups, side-effects), and you want the visible text
to keep streaming through tool rounds without the client losing its
event stream.

## Architecture
- One HTTP endpoint returns `text/event-stream` (SSE).
- Inside the handler, run a loop bounded by `MAX_TOOL_ROUNDS` (4 is the
  default in this codebase). Each iteration:
  1. Call the provider in stream mode with the current `messages` list
     and the full `tools` schema.
  2. Forward visible deltas to the client as `data: {"type":"token",
     "content": "..."}` lines.
  3. Accumulate `tool_call` deltas locally (provider streams them as
     index/name/args fragments — concatenate by index).
  4. When the stream finishes, if no tool calls were emitted, break.
  5. Otherwise execute every tool serially server-side, append one
     `{"role":"assistant","tool_calls":[...]}` message and one
     `{"role":"tool","tool_call_id":..,"content":..}` message per call,
     and loop.
- After the loop, send a final `{"type":"text"}` event (and any
  command frames the AI emitted), then close the stream.
- Record each tool invocation `{name, args, row_count, duration_ms,
  result_preview}` into a JSONB column on the assistant message row
  so the admin can audit which slices of data the model pulled in.

## Data model
- `chat_messages.tool_calls_json JSONB NULL` (or per-message JSON
  attached to the assistant turn). Indexed by `conversation_id`.
- Optional: per-tool cost rows in `api_cost_events` keyed by surface
  (visitor_chat vs admin_chat) and the underlying model.

## API surface
- `POST /api/chat` (visitor) — body `{message, history, session_id}`,
  SSE response. Events: `token`, `text`, `command`, `availability`,
  `done`, `error`.
- `POST /admin/api/chat/stream` (admin) — body `{session_id, message,
  attachment_ids?, persona?}`. Adds events: `tool_start`, `tool_end`
  (with `tool: {id, name, args, result_preview, ...}`) so the admin
  UI can render a per-call trace alongside the streamed text.

## Key files
- `app.py` — chat route, tool-call accumulator, `for _round in
  range(max_rounds)` loop (see lines ~16988 and ~19813 for two
  instances of the same pattern).
- `public/script.js` — `chatSendStreaming` consumes the SSE.

## External deps
- OpenAI Python SDK (`stream=True`, `tools=[...]`) or compatible
  provider that yields tool-call deltas in stream mode.

## Pitfalls
- Provider chunks tool-call args as character fragments — concatenate
  per `index` before `json.loads`, otherwise you get partial JSON
  parse errors.
- Forgetting the `max_rounds` cap turns a misbehaving model into an
  infinite tool-call loop and a runaway bill.
- The `tool` role message MUST reference the exact `tool_call_id` the
  assistant emitted, or the next call fails with a 400.
- SSE chunks must flush per token — disable proxy buffering (nginx
  `X-Accel-Buffering: no`) or the client sees a single burst at end.

## Adaptation notes
- Stack-agnostic: any framework that can stream a chunked response
  works (Flask `Response(stream_with_context(...))`, FastAPI
  `StreamingResponse`, Express `res.write`, etc.).
- Bounding loop rounds is the single most important safety knob —
  pick a number based on the deepest legitimate chain your tools
  need; 3–5 covers almost everything.

## Related skills
- `02-partial-json-streaming-decoder.md` — how the client renders
  structured deltas that arrive inside a streamed token field.
- `04-semantic-response-cache.md` — front-loads this loop with a
  cache check before paying the provider.
- `05-human-in-the-loop-approvals.md` — pattern for tools that should
  not auto-execute (`propose_*` instead of `do_*`).
- `09-live-progressive-iframe-render.md` — visual companion that
  consumes the same SSE.
