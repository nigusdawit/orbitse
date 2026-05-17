# Snapshot & Revert for Settings

**Category:** Admin Tooling
**Related:** `auth/*` (admin gating)

## When to use
Your admin dashboard lets operators edit hundreds of settings (theme
tokens, site copy, gallery cards, pricing, layout sections). Sooner or
later someone will save a broken config at 11pm and want it back. A
DB-backed snapshot + one-click revert is cheap insurance.

## Architecture
- Two flavours work; pick one based on blast radius:
  - **Full-table snapshot** — JSON-serialise an entire table (e.g.
    `site_settings`, `theme`, `page_sections`) into a `snapshots` row
    on every save. Revert = `DELETE FROM table; INSERT ... FROM
    snapshot_json`. Simple, lossless, can be storage-heavy.
  - **Row-level audit** — write one row per change to an audit table
    with `(table_name, row_id, before_json, after_json, actor, ts)`.
    Revert = `UPDATE ... SET col = (before_json->>col)`. More queries,
    cheaper storage, lets you revert one field at a time.
- This template uses the row-level approach via `super_admin_audit`
  (see `migrations/versions/0002_super_admin_audit.py`).
- Revert is gated to authenticated admins (or super-admin) — never
  expose the endpoint publicly. A revert is a privileged write.
- Each revert ALSO writes an audit row ("revert of snapshot N") so
  the chain is fully reversible — including reverting a revert.

## Data model
Recommended minimal table:
```sql
CREATE TABLE settings_snapshots (
  id SERIAL PRIMARY KEY,
  table_name TEXT NOT NULL,
  row_id INTEGER,                  -- NULL for whole-table snapshots
  before_json JSONB,
  after_json JSONB,
  actor TEXT,                      -- admin email or 'system'
  reason TEXT,                     -- optional free-form note
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON settings_snapshots (table_name, row_id, created_at DESC);
```

## API surface
- `GET /admin/api/snapshots/list` — paginated list with table/row filter
  (`app.py:21642`).
- `GET /admin/api/snapshots/<id>` — full snapshot detail
  (`app.py:21665`).
- `POST /admin/api/snapshots/<id>/revert` — apply the `before_json`
  (`app.py:21684`). Returns the new snapshot id created by the revert
  itself so the UI can show "undo this revert".

## Key files
- `app.py:21642` — list endpoint
- `app.py:21665` — detail endpoint
- `app.py:21684` — revert endpoint
- `app.py:13555` — `_admin_execute_revert` — the actual apply step
- `migrations/versions/0002_super_admin_audit.py` — schema

## External deps
None. Pure Postgres JSONB + Flask.

## Pitfalls
- **Idempotency** — guard with a unique constraint on `(table_name,
  row_id, after_hash)` or skip writing a snapshot when nothing changed,
  otherwise every "Save" with no edits doubles your row count.
- **Foreign keys** — reverting a row that another table FK-references
  may fail. Wrap the revert in a transaction and surface a friendly
  error.
- **Schema drift** — a snapshot taken before a column was added contains
  no value for it. Decide policy: leave the new column untouched, NULL
  it, or block the revert.
- **Secrets in snapshots** — if any of the tracked tables hold API
  keys or password hashes, encrypt or exclude those columns from the
  snapshot JSON.
- **Storage growth** — wide tables × frequent edits blow up fast. Add a
  retention sweeper (`DELETE FROM settings_snapshots WHERE created_at <
  now() - interval '90 days'`).

## Adaptation notes
- For multi-tenant SaaS, add `tenant_id` + index on
  `(tenant_id, created_at DESC)` so revert can never cross tenants.
- Allow tagging a snapshot ("v1.0 launch config") for named restores.
- A "compare" view diffing two snapshots side-by-side is high value
  — Postgres JSONB makes the diff a single recursive function.
- Hook the snapshot writer into your storage layer (or a generic
  `with snapshot('site_settings', row_id):` context manager) so
  individual route handlers don't have to remember.

## Adoption checklist
1. Create the `settings_snapshots` (or audit) table.
2. Wrap each editable table's save handler to write a snapshot row.
3. Build the three endpoints (list, detail, revert).
4. Add a retention sweeper.
5. UI: a "History" tab per setting + a one-click "Restore" button that
   shows a diff before applying.
