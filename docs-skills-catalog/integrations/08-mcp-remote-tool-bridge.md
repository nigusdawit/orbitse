# MCP Remote Tool / Server Bridge

## When to use
You want the AI chat (and other in-app agents) to call **remote tools** the operator wires up at runtime — without redeploying. Examples: connect to a customer's CRM via a hosted MCP server, expose internal tools sitting behind a colleague's MCP server, plug in a vendor's MCP service (Linear, GitHub, etc.) so the chatbot can read and act on real data.

The Model Context Protocol (MCP) is the wire format; the bridge stores connections, lists their tools, and exposes those tools to your AI loop as if they were native function-calling tools.

## Architecture
1. **Server config table** — admins add a remote MCP server: URL, transport (HTTP/SSE/streamable), auth type (none / bearer / OAuth), and credentials. OAuth servers persist `oauth_state`, `client_id`, refresh tokens.
2. **Tool discovery** — on save (and periodically), the app does an MCP `list_tools` handshake against the server and caches the result (tool name, description, input schema, audience flags).
3. **Audience filtering** — each cached tool carries `allowed_for_velo` and `allowed_for_admin` flags so the operator decides which surfaces can call which tools.
4. **Chat injection** — when the AI chat tool loop assembles function-calling schemas, it includes every MCP tool the current surface is allowed to use, prefixed with the server name to avoid collisions.
5. **Invocation** — when the AI calls a tool, the bridge translates the function call back into an MCP `call_tool` request against the right server, returns the result to the model, and (because all the chat tools log to `chat_messages.tool_calls_json`) the admin can see exactly which MCP tool ran with what args.
6. **Automation actions** — a `call_skill` action in the IFTTT engine lets admin-built automations invoke MCP tools too, so the tool surface is reusable beyond chat.

## Data model
- `mcp_servers` — id, tenant_id, name, url, transport, auth_type, auth_config JSONB (credentials, OAuth state), enabled, last_synced_at, last_error.
- `mcp_tools_cache` — id, mcp_server_id, tool_name, description, input_schema JSONB, allowed_for_velo, allowed_for_admin.
- `agent_skills` / `chat_messages.tool_calls_json` — invocation logging (shared with native tools).

## API surface
- `/admin/api/mcp/servers` — GET / POST / PUT / DELETE.
- `/admin/api/mcp/servers/<id>/tools` — re-sync the tool cache.
- OAuth callback route for OAuth-flow servers.

## Key files
- `app.py` — `mcp_servers` table setup (~line 2080), `mcp_tools_cache` (~line 2105), admin CRUD routes (~lines 22284–22569), chat-loop injection (~lines 10659–10692).

## External deps
The MCP SDK (or a hand-rolled JSON-RPC client over your chosen transport). `httpx` for HTTP transport, an SSE client for SSE servers.

## Pitfalls
- **Name collisions.** Two MCP servers can both expose `search`. Always namespace the function name (`<server_slug>__search`) before handing the schema to the LLM.
- **Schema drift.** MCP tool schemas can change server-side. Re-sync periodically and surface diffs to the admin so a removed tool doesn't keep showing up in the AI's options.
- **Credential rotation.** OAuth tokens expire; bake refresh into the call path, not just into a periodic sweep.
- **Audience flags must be checked at call time,** not just at schema-injection time. A stale chat session could try to call a tool the admin just revoked.
- **Tool latency.** Remote MCP calls can be slow; the AI loop will wait. Cap timeout and surface "tool failed (timeout)" so the model can recover and tell the user.
- **PII leak.** Tool outputs go straight to the model context; admin should be able to mark a tool "log args only, redact result" if it returns sensitive data.

## Adaptation notes
- The pattern generalizes to *any* remote tool protocol — gRPC, OpenAPI, custom JSON-RPC. Treat MCP as one transport.
- For local-process tools (a stdio MCP server packaged with the app), the same registry works — the transport is just "spawn this subprocess."
- Pair with the per-tool cost ledger to attribute spend to the right tenant when the remote MCP server itself bills (e.g. paid GitHub API quota).

## Adoption checklist
- [ ] Decide MCP transport(s) you'll support — HTTP+SSE covers most.
- [ ] Build the server config table with `auth_type` + `auth_config JSONB`.
- [ ] Build the tool cache table and a sync endpoint.
- [ ] Add the OAuth callback route and persist state per server.
- [ ] Inject cached tool schemas into the AI function-calling list at call time, namespaced.
- [ ] On AI tool-call dispatch, translate back to an MCP `call_tool` and return the result.
- [ ] Log invocations to your existing tool-call audit trail.
- [ ] Expose audience flags in the admin UI so operators can scope tools per surface.
