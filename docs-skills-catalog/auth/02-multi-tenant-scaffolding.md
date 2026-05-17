# Multi-Tenant Scaffolding (single-tenant today, plural-ready)

One-line: Stand up the `tenants` / `plans` / `tenant_features` tables and a `current_tenant_id()` indirection now, so the codebase can grow into multi-tenant later without touching call sites.

Category: Auth & Multi-tenancy

## When to use
- You are building a single-customer SaaS template that you intend to clone or sell to many customers eventually.
- You want plan-based feature gating (Solo / Growth / Enterprise) and per-customer feature toggles from day one, without committing to row-level multi-tenancy on every table yet.
- You want the cost ledger and per-tenant settings to already key on `tenant_id`, so when the second customer arrives the data model does not move.

Do NOT use this if:
- You already need real isolation between customers — this scaffold keeps everything in one schema with `tenant_id` columns; row-level security and per-tenant DBs are out of scope.
- You will never have a second customer. The indirection still costs you a join.

## Architecture
1. Three small tables describe the tenant world:
   - `plans` — tier definitions (`solo`, `growth`, `enterprise`).
   - `tenants` — one row per customer site. Today exactly one row, `id = 1`.
   - `tenant_features` — `(tenant_id, feature_name) UNIQUE` with an `enabled` bool. Lazy-seeded.
   - `feature_addons` — one-off unlocks layered on top of the plan.
2. Every capability check goes through `tenant_has_feature(name, tenant_id=None)`. Unknown names fail OPEN (return True) so adding a new gate to code without an immediate registry update never breaks production.
3. `_FEATURE_REGISTRY` is the source of truth list `(name, label, plan_tier, default_enabled, group)`. The Plans & Features admin UI renders exactly this list.
4. `current_tenant_id()` is a one-line function that today returns `1`. Every call site uses it instead of hard-coding the integer, so swapping in a host-header / session lookup later is a single-file change.
5. A tiny per-process cache (`_FEATURE_CACHE`, 30 s TTL) makes flag checks cheap on hot paths. An `invalidate_tenant_features_cache(tenant_id)` helper is called from the PATCH endpoint that flips a flag.
6. Cost-ledger and chat-attachment tables already carry `tenant_id INTEGER NOT NULL DEFAULT 1` so a second tenant slots in without a schema change.

## Data model
```sql
CREATE TABLE plans (
  id SERIAL PRIMARY KEY,
  slug VARCHAR(40) UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE tenants (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL DEFAULT 'Default Tenant',
  plan_id INT REFERENCES plans(id) ON DELETE SET NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE tenant_features (
  id SERIAL PRIMARY KEY,
  tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  feature_name VARCHAR(80) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(tenant_id, feature_name)
);

CREATE TABLE feature_addons (
  id SERIAL PRIMARY KEY,
  tenant_id INT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  feature_name VARCHAR(80) NOT NULL,
  granted_at TIMESTAMP DEFAULT NOW(),
  note TEXT NOT NULL DEFAULT '',
  UNIQUE(tenant_id, feature_name)
);
```

Seed: three rows in `plans`, one row in `tenants (id=1, plan='growth')`, and a bulk-insert of every `_FEATURE_REGISTRY` entry into `tenant_features` with `ON CONFLICT DO NOTHING`.

## API surface
- `GET /admin/api/tenant/features` — full grid: registry × current tenant enabled state. Used by the Plans & Features tab.
- `PATCH /admin/api/tenant/features/<name>` — body `{ "enabled": bool }`. Flips the flag, invalidates the cache.

Internal Python:
- `current_tenant_id() -> int`
- `tenant_has_feature(name, tenant_id=None) -> bool`
- `list_tenant_features(tenant_id=None) -> list[dict]`
- `invalidate_tenant_features_cache(tenant_id=None)`

## Key files in this codebase
- `app.py` — table create + seed in `init_db()` (~lines 2120–2247).
- `app.py` — registry and lookup helpers (~lines 3940–4100).
- `app.py` — admin endpoints (~lines 38350–38440).

## External dependencies
- None beyond the existing Postgres + `psycopg2` setup.

## Pitfalls
- **`current_tenant_id()` always returns 1.** Until you wire host/session resolution, multi-tenant is structural only — two customers sharing the same install will collide. Audit every write path before flipping that to a real lookup.
- **Fail-open on unknown features.** Convenient for development; risky if a typo in `tenant_has_feature("voicee")` silently allows a paid feature. Add a lint pass that asserts the string appears in `_FEATURE_REGISTRY`.
- **Cache invalidation is per-process.** With multiple Gunicorn workers, a flag flip is visible to the worker that handled the PATCH instantly and to other workers within `_FEATURE_CACHE_TTL_SEC` (30 s). Acceptable for ops UI, not for monetized hard cutoffs.
- **Lazy-seed race.** Two concurrent first-checks for the same `(tenant, feature)` both call `_ensure_tenant_feature_row` — the UNIQUE constraint + `ON CONFLICT DO NOTHING` makes it safe, but expect noise in DB logs on cold start.
- **`feature_addons` is defined but unused** in the read path. If you start granting one-off unlocks, extend `tenant_has_feature` to OR the addon row in.

## Adaptation notes
- To resolve tenant by host: replace `current_tenant_id()` with a lookup that maps `request.host` (or a subdomain) to `tenants.id`, with a sane fallback for the admin dashboard.
- To resolve by session: store `tenant_id` in the admin session at login, read it from `session.get("tenant_id")`. Add an admin-impersonation guard.
- To enforce row isolation: add `tenant_id` to every domain table (gallery_cards, services, ...), set `DEFAULT current_tenant_id()` via the app layer, and add `WHERE tenant_id = %s` to every read/write. Consider Postgres RLS once the column is universal.
- Plan tiers are purely cosmetic today — they label registry entries. To enforce them, gate the PATCH endpoint by `plan.sort_order >= feature.plan_tier_sort_order`.

## Cross-references
- `01-fernet-secret-encryption.md` — when you go multi-tenant, partition the encryption key by tenant id (derive per-tenant from a master).
- `03-admin-gate.md` — session bag is the natural place to stash the resolved `tenant_id`.
- `04-super-admin-audit.md` — feature flips are exactly the kind of event the super-admin audit log already covers.
