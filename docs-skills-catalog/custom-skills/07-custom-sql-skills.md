# Custom SQL Skills (Admin-Authored Read-Only Tools for the AI)

## When to use
Your operator wants the AI to answer questions like "how many people booked the spa last week" or "what's the most popular menu item this month" — but those queries don't fit any of your built-in lookup tools, and you don't want to ship a new code release every time a different operator asks a new question. Custom SQL skills let admins author a parameterized read-only SELECT, give it a tool name and description, and have it appear automatically in the AI's tool list on the next chat turn.

## Architecture
Two tables work together:

- `custom_sql_skills` — one row per admin-authored SQL tool. Stores `name`, `description`, the `sql_template` (with psycopg2 **named placeholders** `%(arg_name)s`, NOT SQLAlchemy-style `:param`), and `args_schema_json` (JSON-Schema describing the params the AI must supply).
- `agent_skills` — the unified skill catalog. An on-edit sync function (`sync_custom_skills_to_agent_skills`) materializes one `agent_skills` row per custom SQL skill (regardless of enabled state — `enabled` is mirrored onto the `agent_skills.enabled` column so a disabled SQL skill simply becomes a disabled catalog entry, not a missing one). `config_json = {"type":"sql","sql_skill_id":<id>}`. The sync runs at app boot and after every CRUD save on `custom_sql_skills`, `custom_webhook_skills`, and the MCP tables — there is no periodic scheduler tick driving it.

When the chat endpoint builds the OpenAI tool list, it walks every enabled `agent_skills` row. For type `"sql"`, it reads `args_schema_json` from `custom_sql_skills` and emits an OpenAI function-tool descriptor. When the AI calls that tool, the dispatcher:

1. Looks up the linked `custom_sql_skills` row (via `config_json.sql_skill_id` on the `agent_skills` mirror).
2. Refuses to run if the row is disabled, the template is empty, or it contains more than one statement (no `;` allowed mid-template).
3. Binds args into the SQL template **as parameters** using psycopg2 named-parameter style (`%(arg_name)s`), never via string interpolation. The `args_schema_json` is published to the AI as the function-tool schema so the OpenAI API rejects malformed calls before they reach the server — but the executor itself does NOT re-validate args at runtime; if the AI somehow sends extra keys, psycopg2's named-parameter binder will ignore them, and missing required keys will surface as a SQL error.
4. Runs a forbidden-keyword regex against the template (rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, etc.) and refuses to execute if anything matches — this is the first line of defense.
5. Opens a transaction, sets `SET LOCAL statement_timeout = '5s'` and `SET LOCAL transaction_read_only = on`, then executes the template. Postgres will hard-fail any DDL/DML even if a write somehow slipped past the regex.
6. Uses `cur.fetchmany(100)` so even an unbounded `SELECT` returns at most 100 rows back to the AI.
7. Returns `{rows, count}` (rows pass through `_redact_recursive` to scrub secret-named keys). The call is logged into `chat_messages.tool_calls_json` as compact metadata only — `{name, args, rows, ms, error?}` — never the full result body.

## Data model
- `custom_sql_skills(id, name UNIQUE, description, sql_template, args_schema_json, enabled, created_at, updated_at)` — no per-row row_limit; the 100-row cap is enforced in the executor and applies to every skill.
- `agent_skills(id, name, display_name, description, category, builtin BOOLEAN, enabled BOOLEAN, config_json JSONB, ...)` — shared with built-in and webhook/MCP skills; `builtin=false`, `config_json={"type":"sql","sql_skill_id":<id>}`.

## API surface
Admin CRUD:
- `GET /admin/api/custom-sql` — list.
- `POST /admin/api/custom-sql` — create (admin pastes a SELECT and a JSON schema).
- `PUT/DELETE /admin/api/custom-sql/<id>` — edit/delete. There is no dedicated `/test` endpoint — the admin tab calls the same dispatcher path (`_exec_custom_sql`) as the AI to dry-run.

Sync:
- `sync_custom_skills_to_agent_skills()` — called at app boot and from every CRUD save on the custom-SQL, custom-webhook, and MCP tables. No periodic scheduler tick.

Chat-time:
- The shared dispatcher (`SKILL_EXECUTORS["sql"] = _exec_custom_sql`) routes `config_json.type=='sql'` to the executor.

## Key files
- `app.py` — `custom_sql_skills` table init (~line 2053), the four admin CRUD routes (~line 22010+), `_exec_custom_sql` (~line 11000), the `SKILL_EXECUTORS` dispatch map, and `sync_custom_skills_to_agent_skills`.
- `templates/admin/dashboard.html` — Custom SQL Skills tab with the SQL editor, JSON-Schema editor, and Test panel.

## External deps
None beyond psycopg2 (already required by the app).

## Pitfalls
- **NEVER interpolate args into the SQL string.** Always use parameterized queries (`%(param)s` with a dict). A custom skill that does `f"... WHERE name = '{args['name']}'"` is an instant SQL injection — and the AI is the attacker, since it controls the args from arbitrary visitor input.
- **Enforce read-only at the DB level, not just by convention.** Two options: (a) create a separate Postgres role with only `SELECT` grants and a dedicated connection pool, (b) wrap every execute in `BEGIN READ ONLY; <sql>; ROLLBACK;`. Don't rely on "the template starts with SELECT" — `WITH x AS (DELETE ... RETURNING *) SELECT ...` is a SELECT statement.
- **`SELECT * FROM (template) LIMIT N`** breaks if the template ends with `LIMIT` already or with a `;`. Strip trailing `;` and warn the admin in the editor.
- **`args_schema_json` must be validated server-side**, not just trusted from the AI. The admin's schema is the contract; AI-supplied args that violate it should reject the tool call, not pass through.
- **PII leakage.** A "search customers by email" skill returns whatever columns the template SELECTs. Admins routinely SELECT * — train the UI to discourage it, and consider a per-skill column allowlist.
- **Sync drift.** If the admin disables a custom SQL skill but the `agent_skills` mirror still has `enabled=true`, the dispatcher will run a "disabled" tool. Always run `sync_custom_skills_to_agent_skills` on every CRUD save (this codebase has no periodic sync tick — save-time + boot-time invocations are the only way the mirror gets refreshed).
- **Query timeout.** A novice admin will eventually write a Cartesian join. Set a per-tool `statement_timeout` (`SET LOCAL statement_timeout = '5s'`) inside the read-only transaction.

## Adaptation notes
- For multi-tenant: scope every executed query by the tenant_id from the chat session, either via a mandatory `:tenant_id` parameter in the template or by setting a session-local variable that RLS uses.
- A "preview rows" affordance in the admin UI dramatically reduces foot-gun SQL — admins iterate before publishing.
- If you ship more than ~10 custom skills per tenant, consider adding a per-skill execution log so admins can see which AI turns triggered them.
- Composability: a custom SQL skill can be invoked by an automation (see scheduler skills), not just by the AI — same dispatcher.

## Adoption checklist
- [ ] Create `custom_sql_skills` and `agent_skills` tables.
- [ ] Build the dedicated read-only DB role OR the `BEGIN READ ONLY` transaction wrapper.
- [ ] Implement `_execute_sql_skill` with parameterized binding, JSON-Schema arg validation, `LIMIT` enforcement, and statement_timeout.
- [ ] Build the admin CRUD UI with a Test/Dry-Run panel.
- [ ] Implement `sync_custom_skills_to_agent_skills` and call it on every CRUD save.
- [ ] Route `config_json.type=='sql'` in the central dispatcher.
- [ ] Log every execution into `chat_messages.tool_calls_json`.
- [ ] Verify in tests: a DELETE-disguised-as-CTE is rejected by the read-only wrapper.
