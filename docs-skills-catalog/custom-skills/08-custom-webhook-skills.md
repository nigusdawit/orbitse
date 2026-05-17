# Custom Webhook Skills (Admin-Authored HTTP Tools for the AI)

## When to use
Operators want the AI to call into their other systems — book a meeting via Calendly, file a Zendesk ticket, push a row into a Google Sheet, notify their Slack — without you shipping a per-integration adapter. Custom webhook skills let admins paste a URL, configure headers/method/JSON-Schema params, and have the AI call it on the next chat turn. Same dispatcher as built-in tools, same logging, same per-chat enable/disable.

## Architecture
Mirrors the custom SQL skill architecture but the executor is an HTTP request instead of a SQL query.

Two tables:
- `custom_webhook_skills` — one row per admin-authored webhook. Stores `name`, `description`, `url`, `method` (`GET` or `POST` — those are the only two the executor supports), `headers_json` (dict merged into request headers), `args_schema_json` (JSON-Schema for the AI's args), and `timeout_seconds`.
- `agent_skills` — shared catalog. Mirror row carries `config_json = {"type":"webhook","webhook_id":<id>}` (note the key is `webhook_id`, not `webhook_skill_id` — the SQL-skill mirror uses `sql_skill_id` but the webhook-skill mirror is shorter).

When the AI calls a webhook tool, the dispatcher:

1. Resolves the `custom_webhook_skills` row by linked id (`config_json.webhook_id`).
2. The `args_schema_json` is published to the AI as the function-tool schema so the OpenAI API enforces shape at call time — but the executor itself does NOT re-validate at runtime; it forwards whatever args came in. Treat the schema as advisory hardening, not a server-side guard.
3. Runs the URL through the **`_webhook_url_safe` SSRF guard** (defined in `app.py`). The guard parses the URL, requires `http`/`https` only, resolves the hostname, and rejects loopback, link-local, private RFC1918, and IPv6 ULA targets. **DNS pinning**: the resolved IP is reused for the actual connection so the hostname can't re-resolve to a different IP between check and connect (TOCTOU / DNS-rebinding defence).
4. For `POST`, the AI args are sent as a JSON body; for `GET` they are appended as query parameters. There is no Jinja-style body template — the args object is sent verbatim.
5. Makes the request via the `requests` library (imported lazily inside the executor) with the admin's `timeout_seconds`.
6. Returns `{status, ok, json?, body?}` — JSON-parsed when content-type is `application/json`, otherwise the raw body text truncated to 4000 characters before returning. Note this truncation happens *after* `resp.text` is materialized in memory, so a hostile/buggy upstream that streams gigabytes will still be downloaded fully before truncation — there is no upstream-bytes cap. Redirects are disabled (`allow_redirects=False`), and the per-call timeout is hard-capped to 15 seconds regardless of what the admin entered.

Every call is logged into `chat_messages.tool_calls_json` as compact metadata only — `{name, args, rows, ms, error?}`. The full request/response bodies are NOT stored there; the admin sees only that the tool ran, with what args, how long it took, and whether it errored.

## Data model
- `custom_webhook_skills(id, name UNIQUE, description, url, method, headers_json JSONB, args_schema_json JSONB, timeout_seconds INTEGER DEFAULT 10, enabled, created_at, updated_at)`
- `agent_skills` — same shared row as the SQL skill, with `config_json.type='webhook'`.

## API surface
Admin CRUD:
- `GET /admin/api/custom-webhooks`
- `POST /admin/api/custom-webhooks`
- `PUT/DELETE /admin/api/custom-webhooks/<id>`

There is no dedicated `/test` route — the admin tab exercises the same `_exec_custom_webhook` path the AI uses, and the save-time validators reject obviously bad URLs (SSRF guard runs at save AND at call time).

Sync: `sync_custom_skills_to_agent_skills()` materializes the `agent_skills` mirror on every save.

Chat-time: shared dispatcher (`SKILL_EXECUTORS["webhook"] = _exec_custom_webhook`) routes `config_json.type=='webhook'` to the executor.

## Key files
- `app.py` — `custom_webhook_skills` table init (~line 2033), `_webhook_url_safe` SSRF guard (~line 10822), `_exec_custom_webhook` (~line 10911), the four CRUD routes (~line 21867+), the `SKILL_EXECUTORS` dispatch map.
- `templates/admin/dashboard.html` — Custom Webhook Skills tab with URL/method/headers editor.

## External deps
- `requests` — imported lazily inside the executor (not via the app-level `httpx`); chosen because of its straightforward connection-level control needed for DNS-pinning.

## Pitfalls
- **SSRF is the #1 risk.** An admin (or an attacker who compromises an admin account) configures the URL to `http://169.254.169.254/latest/meta-data/iam/...` and the AI will happily exfiltrate cloud credentials. Always:
    - Resolve the hostname to an IP before requesting.
    - Reject if the IP is in any blocked range (loopback, link-local, RFC1918, IPv6 ULA, `0.0.0.0`).
    - Re-resolve and re-check after each redirect.
    - Disable HTTP-to-HTTPS auto-upgrade to anything other than the original host.
- **Don't trust the admin URL — guard it at execute time.** Validating only at save time means a DNS-rebinding attack succeeds: the URL resolves safe at save, unsafe at execute.
- **Header injection.** If you let admins type raw header values and the AI controls args, you can get `Authorization: Bearer {{token}}\r\nHost: evil.com` smuggling. Strip `\r\n` from any rendered header value before sending.
- **Response size cap.** Without one, a webhook returning 50 MB of JSON will OOM your worker. Cap to a few MB; truncate and surface a warning to the AI as the tool result.
- **Timeout enforcement.** A slow webhook stalls the AI turn. Cap the admin's configurable timeout to ~30s; lower for streaming chat to keep total turn latency in check.
- **Secrets in headers.** Admins paste `Authorization: Bearer sk-...` in plaintext. Encrypt `headers_json` at rest (use the same Fernet helper as other secrets — see auth skills) and never echo it back in the admin GET response.
- **Idempotency.** A POST webhook called multiple times (the AI sometimes re-tries on error) can double-charge or double-create. Add an `Idempotency-Key` header sourced from the chat turn id when the admin opts in.

## Adaptation notes
- An "auth profile" library (one-time setup for "Slack Bot", "Zendesk API key", "Custom Bearer") makes the headers UI dramatically less footgun-prone than free-form header pairs.
- For OAuth-protected third parties, prefer a real connector (token refresh, rate-limit handling) over a webhook skill — see the integrations skills folder.
- A "retry on 429" wrapper with exponential backoff turns flaky webhooks into reliable tools, but the timeout cap still applies as a hard ceiling.
- Streaming webhooks (`text/event-stream` responses) are out of scope; webhook skills return one synchronous result.
- For multi-tenant deployments, scope `custom_webhook_skills` rows by tenant_id and namespace the agent_skills mirror name (`tenant_<id>__<name>`) so cross-tenant collisions can't happen.

## Adoption checklist
- [ ] Create `custom_webhook_skills` table; encrypt the `headers_json` column.
- [ ] Reuse (or build) the SSRF guard from your existing URL-fetcher; share it between scraper and webhook skills.
- [ ] Implement `_execute_webhook_skill` with arg validation, URL/body rendering, SSRF check at execute time AND on each redirect, response size + content-type caps, timeout cap.
- [ ] Build the admin CRUD UI with a Test panel that exercises the same dispatcher path.
- [ ] Sync to `agent_skills` on every save.
- [ ] Strip `\r\n` from header values before sending.
- [ ] Log every call into `chat_messages.tool_calls_json`.
- [ ] Verify SSRF blocks 169.254.169.254 and 127.0.0.1, AND that a redirect to one of those is also blocked.
