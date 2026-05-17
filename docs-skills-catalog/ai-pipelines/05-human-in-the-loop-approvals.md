# Human-in-the-Loop Approval Flow

**Category:** AI / LLM Pipelines

## When to use
You expose write capabilities (insert/update/delete, send SMS, change
config) to an AI agent, but you do NOT want auto-execution. Every
mutation must be reviewed and clicked by a human before it lands.

## Architecture
- Two distinct tool families:
  - `propose_*` — the only writes the AI can call. They never mutate
    business tables; they only INSERT into `admin_pending_actions`.
  - `do_*` / direct executors — internal helpers called by the
    approval click handler, NOT exposed to the AI as tools.
- Each `propose_*` tool:
  1. Validates the target table is on an allowlist (no super-admin
     tables, no `chat_messages`, no audit logs).
  2. Validates the target table isn't on the DEDICATED list — those
     have richer per-table proposers (e.g. `propose_create_automation`
     understands trigger types). The generic insert/update must
     refuse and steer the model to the dedicated tool.
  3. Validates field names against the live column list
     (`_admin_table_columns`).
  4. Renders a human-readable preview string ("INSERT INTO X a new
     row with: foo = 'bar', baz = 42").
  5. Inserts one row into `admin_pending_actions` with `status='pending'`
     and returns `{awaiting_approval: True, action_id, preview, ...}`
     so the frontend renders an Approve / Reject card.
- The approval endpoint:
  - Loads the pending row `FOR UPDATE`, refuses if not `pending`.
  - Replays the action against the real table (or invokes the
    dedicated executor).
  - Flips status to `approved` (with `approved_by`, `approved_at`,
    `result_summary`) or `rejected`.
- All mutation audit trail lives in `admin_pending_actions` — you can
  reconstruct exactly what changed, when, by whom, and what the AI
  originally proposed.

## Data model
- `admin_pending_actions (id, session_id, action_type, target_table,
  target_id, payload_json JSONB, preview TEXT, status, result_json
  JSONB, error_text, created_at, decided_at)`.
- Indexes on `(session_id, created_at)` and `(status, created_at)`.
- Approval metadata (who/when) is captured via `decided_at` plus the
  admin session that hit the endpoint; `result_json` carries the
  executor's output. Add `approved_by`/`result_summary` columns when
  porting if you want a richer audit row.

## API surface
- Tool calls (model-facing): `admin_propose_insert`,
  `admin_propose_update`, `admin_propose_delete`, plus dedicated
  per-table proposers.
- HTTP (admin-facing): `GET /admin/api/chat/action/<id>`,
  `POST /admin/api/chat/action/<id>/approve`,
  `POST /admin/api/chat/action/<id>/reject`.

## Key files
- `app.py` — `_admin_create_pending`, `_admin_tool_propose_insert`,
  `_admin_tool_propose_update`, dedicated proposers (`automations`,
  `site_designs`, `site_themes`, MCP servers), `ADMIN_DEDICATED_WRITE_TABLES`
  guard list.

## External deps
None beyond Postgres.

## Pitfalls
- Generic propose tools bypassing dedicated ones is the #1 footgun —
  enforce it in the generic proposer (return an error pointing at the
  dedicated tool, don't silently accept).
- Don't let the AI propose changes to its own audit log, the pending
  actions table, or any auth tables — explicit denylist.
- Race on approve: lock the row `FOR UPDATE` and re-check status, or
  two simultaneous Approve clicks double-apply.
- Show the preview text the AI generated, not a freshly-rendered
  preview from current data — the model proposed against a snapshot
  and the admin needs to see exactly that snapshot.
- Cap payload size — refuse > N KB to stop a runaway model from
  filling the audit table with megabyte JSON blobs.

## Adaptation notes
- The pattern generalizes to any agent with side-effects: "send SMS",
  "post to Slack", "create Stripe refund" — all become `propose_*`
  with a preview and an explicit approve click.
- For lower-risk actions (read-only lookups), keep them as direct
  tools — only mutations need this gate.

## Related skills
- `01-streaming-tool-call-loop.md` — the loop that delivers the
  `awaiting_approval` payload back to the frontend.
- `../auth/03-admin-gate.md` — only authenticated admins can hit the
  approve endpoint.
- `../auth/04-super-admin-audit.md` — for actions that should also
  emit a super-admin audit row on approval.
