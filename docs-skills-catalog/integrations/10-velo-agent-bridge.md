# VELO Agent Bridge (Tenant-Side Orchestrator Hookup)

## When to use
You operate many tenant installs of the same app and you want a **central orchestrator** ("master") that can: ask any install for data, change settings, fire chat messages, send digests, refund orders, etc., across the whole fleet — without SSHing into each install or duplicating an admin UI for the operator team. The bridge lets the orchestrator drive the install via a tiny, capability-registered, audit-logged HTTP surface.

It is *not* a generic RPC — every callable is explicitly registered with a JSON schema, and destructive ones require a two-step confirm-token handshake.

## Architecture
Three pieces:

1. **Outbound client (`velo_client.py`)** — when this install boots / has news to report, it pushes to the master (registration ping, event notifications, periodic heartbeat). Configured by `VELO_MASTER_URL` + `VELO_AGENT_KEY`.

2. **Inbound endpoints (`velo_endpoints.py`)**
   - `POST /api/velo/command` — master invokes a registered capability with `{name, params}`.
   - `POST /api/velo/chat` — master injects a chat message into a session.
   - `GET /api/velo/tools` — master lists what this install can do (handy for the master's own admin UI / agent loop).
   - Every request is authenticated with a `VELO_AGENT_KEY` shared secret (constant-time comparison) plus an HMAC signature over the body.

3. **Capability registry (`velo_handlers.py`)** — concrete handler functions decorated with `@velo_command(name, description, params_schema, requires_confirmation=...)`. Importing the module triggers the decorators, populating a module-level dict the dispatcher reads. Handlers stay clean Python; confirmation, logging, and auth all happen in the dispatcher.

Two safety rails:
- **Confirm-token flow** — handlers marked `requires_confirmation=True` (delete_content, refund_order, manage_plan, send_email, send_sms, etc.) return a token on the first call. The master must echo the token within ~2 minutes to execute. Prevents a bug or a compromised master from wiping data on the first try. Tokens are HMAC'd against `(handler_name, params_signature, expires_at)` and consumed atomically (`DELETE ... RETURNING id` — see the idempotency skill).
- **Audit log** — `velo_audit_log` records every command: name, params, status (`success`/`error`/`needs_confirmation`/`forbidden`), latency, requester IP, error text. The admin's Developer / Audit tab reads from here.

Agent ID registry (`AGENT_IDS`) lets the master target sub-agents within an install (visitor chat vs admin chat vs voice agent) for routed commands.

## Data model
- `velo_audit_log` — id, command_name, params JSONB, status, latency_ms, ip, requester_id, error_text, created_at.
- `velo_confirm_tokens` — id, command_name, params_signature, expires_at; UNIQUE on `(command_name, params_signature)`.
- (No table for the registry itself — it's pure code.)

## API surface
- Inbound: `/api/velo/command`, `/api/velo/chat`, `/api/velo/tools`, `/api/velo/status`.
- Outbound: `velo_client.notify(event_name, payload)`, `velo_client.register()`.
- Code-level: `@velo_command(name, description, params_schema, requires_confirmation=False)`.

## Key files
- `velo_client.py` — outbound notifications / registration.
- `velo_endpoints.py` — inbound routes, auth, confirm-token machinery, dispatcher.
- `velo_handlers.py` — concrete capabilities (get_analytics, manage_features, refund_order, …). Importing this from `app.py` is what populates the registry.
- `app.py` — `VELO_APP_START_TIME` captured at import for uptime reporting.

## External deps
None. Everything is `flask` + `psycopg2` + `hmac` + `requests`.

## Pitfalls
- **Constant-time auth compare.** Use `hmac.compare_digest` for the shared-secret check; a naive `==` is timing-attackable.
- **Confirm-token replay.** The token must be consumed atomically (one statement, one row) — same pattern as the idempotency skill. A `SELECT ... DELETE` two-step lets two masters double-execute.
- **Params schema is the user-input firewall.** Validate against the declared JSON schema before invoking the handler; handlers should never sanitize input themselves.
- **`requires_confirmation` is opt-in per handler.** A new destructive capability that forgets the flag is a footgun. Default-off but loud — code review every new handler for the flag.
- **Audit-log unavailability must not break the bridge.** Wrap the audit insert in try/except; the command should still run.
- **Tenant scoping.** Every handler must be tenant-aware. The dispatcher should set tenant context from the request before invoking the handler.
- **Outbound heartbeats can flood the master if every tenant restarts at once.** Add jitter.

## Adaptation notes
- Replace the master with any orchestrator (internal admin tool, n8n, a chatbot) — the protocol is just authenticated HTTP + JSON.
- Add a per-handler RBAC check on top of `requires_confirmation` if you want different masters to have different permissions.
- Extend the registry decorator to declare cost / latency expectations so the master can pick batch vs interactive routing.

## Adoption checklist
- [ ] Lift the `@velo_command` decorator and dispatcher from `velo_endpoints.py`.
- [ ] Wire `VELO_AGENT_KEY` shared-secret + HMAC body signature.
- [ ] Implement the confirm-token flow with atomic consumption.
- [ ] Add the audit-log table and wrap every command.
- [ ] Mark every destructive handler `requires_confirmation=True`.
- [ ] Validate every params payload against the declared schema.
- [ ] Add outbound `register()` on boot and `notify()` for interesting events.
- [ ] Expose `/api/velo/tools` for orchestrator-side discovery.
