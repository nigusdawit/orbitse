# Edit-and-Rerun Chat Branch

**Category:** Admin Tooling
**Related:** `admin-tooling/04-per-conversation-skills-toggle.md`, `admin-tooling/06-markdown-json-chat-export.md`

## When to use
Operators iterating on an AI assistant want ChatGPT-style "edit my
previous message and rerun from there" without losing the original
thread. The pattern is a **branch**: copy the session up to message N,
let the operator edit message N+1, and continue from the copy. The
original conversation remains intact for comparison.

## Architecture
- One endpoint: `POST /admin/api/chat/sessions/<id>/branch` with body
  `{up_to_message_id: <int>}`.
- Server-side:
  1. SELECT the source session row, INSERT a new row with a fresh UUID,
     copy mutable fields (`system_prompt`, `disabled_tools_json`,
     `use_kb`, model selection).
  2. Set `parent_session_id` + `branched_from_message_id` for breadcrumb
     UI ("← branched from #1234 at turn 5").
  3. SELECT `admin_chat_messages WHERE session_id = src AND id <=
     up_to_message_id ORDER BY id`, then INSERT each copy with the new
     `session_id`. Preserve role/content/tool_calls_json so the AI sees
     the same context.
  4. Return the new `session_id`. The UI navigates to it and the
     operator's next message starts the divergent branch.
- Branching is purely a row copy — no AI call happens during the
  branch operation itself. The next user message triggers a normal
  completion.

## Data model
On `admin_chat_sessions`:
- `parent_session_id` UUID (nullable) — points to the source.
- `branched_from_message_id` INTEGER (nullable) — the last copied
  message id from the parent.

On `admin_chat_messages`:
- The standard `(id, session_id, role, content, tool_calls_json,
  created_at)` shape. No branch-specific columns needed; the new
  session_id is the discriminator.

## API surface
- `POST /admin/api/chat/sessions/<session_id>/branch` body
  `{up_to_message_id}` → `{new_session_id}` (`app.py:18512`).
- (Recommended) `GET /admin/api/chat/sessions/<id>/branches` to render
  a sibling list.

## Key files
- `app.py:18512` — `admin_chat_session_branch` route
- `app.py:18514` — branch logic (row + messages copy)
- `app.py:1956` — `admin_chat_sessions` schema

## External deps
None.

## Pitfalls
- **Transaction wrap.** Session insert + N message inserts must be one
  transaction or a crash leaves an orphan empty session.
- **Tool-call state.** If a message in the copied prefix is an
  `assistant` message with `tool_calls`, you must also copy the matching
  `tool` role messages or the model rejects the conversation. Copy by
  id range, not by role filter.
- **System prompt drift.** Copy the system prompt verbatim — if the
  operator edits the live system prompt later, the branch should keep
  its frozen copy so the rerun reproduces.
- **Cost attribution.** Branches multiply spend. Charge the same
  tenant; surface "branched conversations" in the cost dashboard.
- **Avoid deep recursion limits.** A branch of a branch of a branch is
  fine, but UIs that render the full tree should cap depth or render
  as a flat list.

## Adaptation notes
- For "regenerate this turn" (no edit), branch at the LAST user message,
  drop the trailing assistant reply, and immediately invoke the AI on
  the new session. Same primitive.
- For a Git-style merge ("I like both branches, merge them"), there is
  no clean primitive — concatenate is the practical answer.
- If you store embeddings or per-session caches keyed on session_id,
  the new branch starts cold; that's correct but slow on the first turn.

## Adoption checklist
1. Add `parent_session_id` + `branched_from_message_id` columns.
2. Implement the branch endpoint: SELECT, INSERT session, INSERT
   messages — all in one transaction.
3. UI: a "↳ Edit & rerun" button on every user message that calls
   branch then navigates to the new session.
4. UI: a "branched from" breadcrumb at the top of branched sessions
   so operators can hop back to the original.
