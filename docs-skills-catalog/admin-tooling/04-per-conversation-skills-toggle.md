# Per-Conversation Skills Toggle (`disabled_tools`)

**Category:** Admin Tooling
**Related:** `ai-pipelines/*` (tool-calling loop), `admin-tooling/05-edit-and-rerun-chat-branch.md`

## When to use
Your AI assistant exposes a catalog of OpenAI function-calling tools
(`lookup_gallery`, `lookup_services`, `lookup_web`, `send_sms`, ...) and
some conversations should run with a subset disabled — for testing,
for cost control, for "don't let the AI book anything in this thread",
or to compare answers with/without the web-search tool.

## Architecture
- One JSONB column on the chat-session row: `disabled_tools_json`
  (text[] or JSONB array of tool names).
- At chat-completion time, the orchestrator builds the OpenAI `tools`
  array by FILTERING the global catalog through `disabled_tools_json`
  for that session. The model literally cannot call a tool it never
  sees.
- A `GET /admin/api/chat/skills` endpoint returns the catalog with a
  `disabled` flag per tool for the current session, so the UI can
  render a list of checkboxes with current state.
- A `PATCH /admin/api/chat/sessions/<id>` accepts `{disabled_tools:
  [...]}` and persists the new array. No need to mutate any in-flight
  request — the next turn picks up the new filter.
- "Disabled" is per-session, not per-tenant: each conversation has
  its own toggle state.

## Data model
On `admin_chat_sessions` (`app.py:1956`):
- `disabled_tools_json` JSONB DEFAULT `'[]'::jsonb` — array of tool
  name strings (e.g. `["lookup_web_search","send_sms"]`).

The global catalog is whatever your AI tool registry exposes
(typically a Python dict `{tool_name: schema}` defined in one
module).

## API surface
- `GET /admin/api/chat/skills?session_id=<uuid>` — returns
  `[{name, description, disabled: bool}, ...]` (`app.py:18647`).
- `PATCH /admin/api/chat/sessions/<id>` — body
  `{disabled_tools: ["..."]}` (`app.py:18244`).
- Internal: `chat_completion(...)` filters the catalog before
  building the OpenAI request.

## Key files
- `app.py:1956` — `admin_chat_sessions` table
- `app.py:18174` — `disabled_tools_json` read/parse helper
- `app.py:18244` — PATCH session endpoint
- `app.py:18647` — GET skills endpoint

## External deps
None beyond your existing OpenAI / Anthropic client.

## Pitfalls
- **Validate against the live catalog** on PATCH — silently storing
  unknown tool names rots over time. Reject with 400.
- **Don't filter post-response.** If the AI calls a "disabled" tool
  you forgot to filter out, your only recourse is to refuse mid-stream
  — ugly UX. Filter the catalog BEFORE sending the request.
- **Persist the snapshot per assistant turn** if you want repro: which
  tools were available influences the response. Store the filtered
  tool list in `tool_calls_json` next to the call log.
- **System-message coupling** — if your system prompt enumerates tools
  ("you have access to: ..."), regenerate that section from the same
  filtered catalog or the AI will hallucinate calls to removed tools.

## Adaptation notes
- For a "billing tier" gate (free vs paid features), apply a TENANT-level
  filter on top of the session-level one — intersection wins.
- For A/B testing, randomly disable one tool per session and log
  outcomes.
- Skill groups (e.g. "all `send_*` tools") are easy: store
  `disabled_groups` alongside `disabled_tools` and expand at filter time.

## Adoption checklist
1. Add `disabled_tools_json` to the session table.
2. Wrap your tool-catalog build with a filter step keyed on the
   session row.
3. Add the GET/PATCH endpoints.
4. Add a "Skills" modal in the chat UI listing every tool with a
   checkbox; PATCH on change.
5. Decide system-prompt policy: regenerate-from-filter (recommended)
   or leave static (simpler but the AI may attempt disabled calls).
