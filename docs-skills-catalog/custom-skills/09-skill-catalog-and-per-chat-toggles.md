# Unified Skill Catalog & Per-Chat Toggles

## When to use
You ship built-in AI tools, you let admins author custom SQL and webhook tools, and you cache tools exposed by MCP servers — and you want all of them to live in *one* registry that the chat endpoint walks to build the OpenAI tool list. You also want the admin (and, optionally, the visitor) to be able to disable individual skills per chat session — for example, turning off the slow web-search tool during a quick conversation, or hiding the RAG tool when the admin wants the bare model.

## Architecture
**One table is the canonical registry**: `agent_skills`. Every tool — built-in `lookup_*`, custom SQL, custom webhook, and per-MCP-tool mirror — has exactly one row. The row carries:

- `name` (the function-tool name the AI sees: e.g. `lookup_blog`, `mcp__github__list_issues`, `custom_sql_top_bookings`).
- `display_name`, `description`, `category` — admin UI metadata.
- `builtin BOOLEAN` — true for built-in lookups (`lookup_*`), false for custom/MCP rows.
- `enabled BOOLEAN` — global on/off (admin can disable site-wide).
- `config_json JSONB` — discriminator + linked id: `{"type":"webhook","webhook_id":42}` (note: `webhook_id`, not `webhook_skill_id`), `{"type":"sql","sql_skill_id":7}`, `{"type":"mcp","server_id":3,"tool":"list_issues"}`, or absent for built-in.

A central sync function `sync_custom_skills_to_agent_skills()` materializes the mirror rows for custom SQL, custom webhook, MCP tools, and the KB sentinel. It runs at app boot AND from every relevant admin CRUD save (custom-sql, custom-webhook, MCP). There is no periodic scheduler tick — drift is prevented purely by save-time + boot-time invocations. Built-in rows are seeded on app boot from a hardcoded list (`CHAT_TOOLS`).

**Per-chat toggles** live on `admin_chat_sessions`:
- `disabled_tools_json JSONB` — array of `agent_skills.name` strings the user has turned off in this conversation.
- `use_kb BOOLEAN` — special-case toggle for the auto-RAG injection path (see rag-voice skills).

At chat-turn time, the endpoint:

1. Reads every enabled `agent_skills` row.
2. Removes any whose `name` is in the session's `disabled_tools_json`.
3. For built-in rows, picks the matching OpenAI tool descriptor from a hardcoded map.
4. For type `"webhook"` / `"sql"` / `"mcp"`, fetches the linked row's `args_schema_json` and emits a fresh OpenAI tool descriptor on the fly.
5. Passes the result to the streaming completion as the `tools` parameter.

When the AI calls a tool, the dispatcher reads back the same row, branches on `config_json.type`, and routes to the appropriate executor.

## Data model
- `agent_skills(id, name UNIQUE, display_name, description, category, builtin, enabled, config_json, created_at, updated_at)` — indexed on `enabled` and `category`.
- `admin_chat_sessions.disabled_tools_json JSONB DEFAULT '[]'::jsonb`
- `admin_chat_sessions.use_kb BOOLEAN DEFAULT TRUE`
- `chat_messages.tool_calls_json JSONB` — per-message log of which tools fired, with args + row count + duration. Surfaced beside each AI bubble in admin Chat History.

## API surface
- `GET /admin/api/chat/skills?session_id=...` — returns the full skill catalog with `enabled` (global) and a hint about which are currently disabled-in-session. Powers the admin's Skills modal.
- `PATCH /admin/api/chat/sessions/<session_id>` — **single endpoint** that accepts any subset of `{title, pinned, model, system_prompt_override, disabled_tools, use_kb}` in the body. The per-session skill toggles are sent as `{"disabled_tools": ["tool_name_a", "tool_name_b"]}` (stored in `disabled_tools_json` after validation/capping). The KB toggle goes through the same endpoint as `{"use_kb": true|false}`. There are no separate `/skills` or `/use-kb` sub-routes.
- `PUT /admin/api/skills/<id>` — global edit of any `agent_skills` row, including flipping `enabled` on a built-in. This is the "flip any agent_skills row" endpoint; the per-skill admin tabs use it under the hood for the enable/disable toggles.
- `DELETE /admin/api/skills/<id>` — deletes the row, but **rejects built-in skills with HTTP 400** ("Builtin skills cannot be deleted — they are defined in code and would reappear on next restart. Disable the skill instead."). To hide a built-in, PATCH it to `enabled=false` instead.

Internal:
- `sync_custom_skills_to_agent_skills()` — idempotent mirror sync, called at app boot and from every CRUD save on `custom_sql_skills`, `custom_webhook_skills`, and the MCP tables. No periodic scheduler tick.
- `SKILL_EXECUTORS` dict (`{"webhook": _exec_custom_webhook, "sql": _exec_custom_sql, "mcp": _exec_mcp_tool}`) — single dispatch map; built-in tools have their own direct handlers keyed by name.

Mirror config-json shapes (`agent_skills.config_json`) — same row, different `type`:
- SQL: `{"type":"sql","sql_skill_id":<custom_sql_skills.id>}`
- Webhook: `{"type":"webhook","webhook_id":<custom_webhook_skills.id>}` — note the key is `webhook_id`, not `webhook_skill_id`.
- MCP: `{"type":"mcp","server_id":<mcp_servers.id>,"tool":"<remote_tool_name>"}`

## Key files
- `app.py` — `agent_skills` table init, `CHAT_TOOLS` built-in registry, `sync_custom_skills_to_agent_skills`, the dispatcher, and the four skill-catalog routes above.
- `templates/admin/dashboard.html` — Skills modal launched from the chat sidebar, with per-session toggles + the KB toggle.

## External deps
None beyond the OpenAI client.

## Pitfalls
- **Tool-list-too-big.** OpenAI tools count toward prompt tokens; >40 tools materially raises per-turn cost AND lowers model accuracy (the model gets choice paralysis). Group rarely-used tools under a `lookup_anything` meta-tool, or auto-hide tools below a "score" threshold.
- **Stale mirror rows.** If a sync runs but the admin then deletes a `custom_sql_skills` row out-of-band (e.g. a manual DELETE in psql), the `agent_skills` mirror still exposes the tool and the dispatcher will 500 when it executes. Make `_execute_*_skill` return a friendly "skill not found" tool result instead of raising.
- **Per-session disable hides AI errors.** If the AI repeatedly calls a tool the user disabled in-session, you'll see "tool not in list" model errors. Either filter retroactively (return an empty result with a "this tool is disabled" message), or expose the disable state in the system prompt so the model knows.
- **Name collisions.** Custom skills must not share names with built-ins. Enforce uniqueness via the `UNIQUE(name)` constraint; in multi-tenant, namespace custom names (`tenant_<id>__<name>`).
- **Permission scope.** The catalog is admin-managed; visitors shouldn't be able to enumerate webhook URLs via the catalog endpoint. Keep all `/admin/api/chat/skills*` routes behind `@admin_required`.
- **Logging volume.** `tool_calls_json` can balloon on conversations with many lookups. Truncate per-call payloads at write time (e.g. keep first 2 KB of each result preview) — the admin only needs to know WHAT was called and HOW MUCH came back, not the full body.

## Adaptation notes
- The category column lets you group skills in the UI (`content`, `commerce`, `comms`, `system`); use it as the secondary order key in the OpenAI tools list so related tools sit together.
- For a "skill marketplace" feel, add a `source` column (`builtin`, `custom`, `mcp`, `installed`) and let admins one-click install vetted skill bundles.
- A "skill recommendation" can run on top of the catalog: at chat-turn time, ask a small model "given the user message, which 6 of these N tools are most likely needed?" and pass only those to the main completion. Cuts tokens dramatically when the catalog grows.
- The same registry can drive a non-chat surface: an admin-side "run this tool by hand" panel that exercises the dispatcher directly.

## Adoption checklist
- [ ] Create `agent_skills` with the columns above; seed `builtin=true` rows on boot from a hardcoded list.
- [ ] Add `disabled_tools_json` and `use_kb` to `admin_chat_sessions`.
- [ ] Add `tool_calls_json` to `chat_messages`.
- [ ] Implement `sync_custom_skills_to_agent_skills()` and call it from app boot AND every custom/MCP CRUD save (no periodic tick needed).
- [ ] Build the central dispatcher; route on `config_json.type`.
- [ ] Build the chat-time tool-list builder that walks `agent_skills` and filters by `disabled_tools_json`.
- [ ] Build the `/admin/api/chat/skills*` routes and the admin Skills modal.
- [ ] Truncate tool-call log payloads at write time.
- [ ] Verify the tool list stays under your model's practical limit; add grouping/recommendation if it grows.
