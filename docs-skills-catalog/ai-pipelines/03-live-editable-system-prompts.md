# Live Admin-Editable System Prompts

**Category:** AI / LLM Pipelines

## When to use
Non-developers need to tune the AI's voice, scope, and behavior
without redeploys, and per-conversation overrides should also be
possible (e.g. "answer in French" pinned to one session).

## Architecture
- A singleton settings row (`chatbot_settings` id=1 here) carries the
  default `system_prompt TEXT NOT NULL DEFAULT ''`.
- On every chat turn, the server composes the system message as:
  `[default prompt] + [session override?] + [auto-injected context]`.
  The auto-injected portion is a compact SITE INDEX (names/slugs only),
  brand identity tokens, layout snapshot, and a TOOL USAGE block —
  the bulky details live behind lookup tools so token cost stays
  ~constant as the site grows.
- Per-conversation override stored on the session row
  (`system_prompt_override TEXT NOT NULL DEFAULT ''`).
- Admin UI exposes a textarea + reset button for the default and a
  "pin override" affordance per chat session.

## Data model
- `chatbot_settings (id=1, system_prompt TEXT, ...)` — singleton.
- Per-session override column on the chat-session table.
- Sample seed/sample prompt kept in code (`SAMPLE_SYSTEM_PROMPT`) so a
  fresh install isn't blank.

## API surface
- `GET /api/chatbot-settings` — public read for the visitor frontend.
  **WARNING:** in this codebase the route currently returns
  `SELECT *` from `chatbot_settings`, which exposes `system_prompt`
  to anyone. When porting this pattern, either project a column
  whitelist (e.g. `id, enabled, embed_mode, embed_url`) or move the
  prompt to a separate admin-only table — do not leave the live
  prompt readable by the public.
- `GET /admin/api/chatbot-settings` and `PUT /admin/api/chatbot-settings`
  — admin read/write (note: PUT, not PATCH).
- Session override is editable through the admin chat session manager.

## Key files
- `app.py` — settings table init, `SYSTEM_PROMPT` sample, prompt
  composition inside the chat handler.

## External deps
None.

## Pitfalls
- Never echo the system prompt into a visitor-facing endpoint — leak
  surface for jailbreak attacks.
- Stuffing the entire site catalog inline grows tokens with content;
  push details behind lookup tools (see related skill).
- Caching: invalidate any prompt-derived cache (semantic response
  cache, embedded site index) when the prompt changes — bump a
  `content_version` integer rather than purge tables.
- TEXT columns are unbounded — add a soft length cap in the admin UI
  so accidental paste of a 100k transcript doesn't pin the AI on a
  massive prompt forever.

## Adaptation notes
- The "compact index + lookup tools" pattern scales much better than
  RAG for small structured sites. For unstructured docs, prefer RAG.
- For multi-tenant apps, key the singleton by `tenant_id` and read
  the row in the request's tenant context.

## Related skills
- `01-streaming-tool-call-loop.md` — consumes the composed prompt.
- `../rag-voice/` (Batch 3) — when the bulky context is unstructured
  documents instead of structured tables.
- `04-semantic-response-cache.md` — uses `content_version` to
  invalidate on prompt edits.
