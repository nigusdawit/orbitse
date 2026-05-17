# Super-Admin Lock + Audit Log

One-line: An optional second-factor that gates the most dangerous admin tabs (secrets editor, plans & features, devconsole, performance) behind an env-var key, with a 30-minute sliding-TTL unlock, per-IP throttle, and an append-only audit table that records every unlock attempt, manual lock, auto-lock on TTL expiry, and logout.

Category: Auth & Multi-tenancy

## When to use
- You have admin sections that, if abused, could leak credentials or break the install (secret editor, feature flags, LLM provider swap, image-variant regeneration, SMTP/SMS test endpoints).
- You want a "step-up auth" layer without pulling in MFA libraries.
- You want a forensics trail that survives process restarts and is safe to expose to any logged-in admin (no keys, no session tokens — only IPs, UAs, action labels, outcomes).

Do NOT use this when:
- You only have one tier of admin access. Keep it simple.
- You want true MFA. This is a shared secondary password, not TOTP/WebAuthn.

## Architecture
1. `SUPER_ADMIN_KEY` env var holds the optional second factor. Unset → lock is OFF, base admin password suffices (fail-safe so an operator can never lock themselves out by accident).
2. `_SUPER_ADMIN_PROTECTED_PREFIXES` lists the API paths that require the unlock: secrets editor, performance tools, devconsole, tenant features. `before_request` hook `_enforce_super_admin_lock`:
   - Skips non-admin sessions, anonymous traffic, webhooks.
   - Skips the `/admin/api/super-admin/*` family itself (status/unlock/lock/audit must remain reachable while locked).
   - If a protected prefix matches and the session is not unlocked, returns JSON 401 `{ "error": "super_admin_required" }`.
   - If unlocked, refreshes the unlock timestamp (sliding TTL).
3. Unlock TTL is 30 min of inactivity. When a request first observes an expired unlock, it pops the stale session timestamp and writes one `auto_lock / ttl_expired` audit row (with the original `unlocked_at` in the `reason` field). A per-process dedupe dict prevents concurrent stale requests from each emitting their own duplicate row.
4. Failed unlock attempts go through a separate per-IP throttle (5 failures per 5 min). Successes clear the counter.
5. Equality on the submitted key uses `secrets.compare_digest`. The key is read from the env at call time so a hot-rotate via the secrets editor takes effect immediately.
6. Every action emits one row into `super_admin_audit`. Best-effort write — wrapped in `try/except` and swallowed so an unavailable audit table never breaks the auth flow.

## Data model
```sql
CREATE TABLE super_admin_audit (
  id         SERIAL PRIMARY KEY,
  ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ip         TEXT,
  user_agent TEXT,
  action     TEXT NOT NULL,           -- 'unlock' | 'lock' | 'auto_lock'
  outcome    TEXT NOT NULL,           -- 'success' | 'invalid_key' | 'throttled'
                                      -- | 'manual' | 'ttl_expired' | 'logout'
  reason     TEXT                     -- optional context, e.g. 'unlocked_at=…'
);
CREATE INDEX idx_super_admin_audit_ts ON super_admin_audit (ts DESC);
```

Append-only by convention; no UPDATE/DELETE in app code. Owned by Alembic migration `0002_super_admin_audit`.

## API surface
All four endpoints carry `@admin_required` (logged-in admin only) and live under `/admin/api/super-admin/*`, which is exempt from the lock itself:
- `GET /status` → `{ enabled, unlocked, expires_at, ttl_seconds, protected_prefixes }`.
- `POST /unlock` body `{ "key": "..." }` → `{ ok, enabled, unlocked, expires_at }` on success, 401 invalid_key, 429 throttled.
- `POST /lock` → manual re-lock (e.g. operator clicks "Lock now").
- `GET /audit?limit=N` (default 50, cap 200) → recent audit rows.

## Key files in this codebase
- `app.py` — throttle dicts + dedupe (`_SUPER_ADMIN_ATTEMPTS`, `_SUPER_ADMIN_AUDIT_RECENT_EXPIRY`) (~lines 395–460).
- `app.py` — `_audit_super_admin` writer (~lines 463–500).
- `app.py` — protected prefix list, `_super_admin_*` helpers, `_enforce_super_admin_lock` before-request (~lines 5278–5380).
- `app.py` — four endpoints + `admin_logout` audit hook (~lines 5265–5479).
- `migrations/versions/0002_super_admin_audit.py` — table + index.

## External dependencies
- None beyond Flask, psycopg2, and Python stdlib (`secrets`, `threading`, `time`).

## Pitfalls
- **Fail-open when key unset.** This is deliberate (operator lockout protection) but means leaving `SUPER_ADMIN_KEY` blank in prod silently disables the entire lock. Add a startup warning if you flip more than one risky feature flag and the lock is off.
- **In-process throttle / dedupe** does not span workers. A multi-Gunicorn deploy can produce a small number of cross-process duplicate `auto_lock / ttl_expired` rows. Audit reader should dedupe on `(ip, action, outcome, reason)` if it matters.
- **Best-effort writes mean some events may be missing** if Postgres is briefly unreachable. The auth flow never fails because of the log — by design.
- **TTL is sliding.** Casual polling of `/status` is excluded from refresh, but any other protected-endpoint hit during the 30-minute window extends it. An idle tab with auto-refresh logic on a protected endpoint will keep the unlock alive forever.
- **`reason` is a free-form string.** Do not parse it programmatically — only `unlocked_at=…` is currently structured.
- **The audit endpoint is open to any logged-in admin.** Data is non-secret (no keys), but if you later store anything sensitive in `reason`, gate the endpoint.

## Adaptation notes
- Swap the env-var key for TOTP: replace `_super_admin_key()` and `secrets.compare_digest` with a TOTP verify, keep the rest of the machinery (throttle, audit, sliding TTL) verbatim.
- Add new protected prefixes by appending to `_SUPER_ADMIN_PROTECTED_PREFIXES`. The `before_request` hook needs no changes.
- For multi-worker durability of the throttle, replace `_SUPER_ADMIN_ATTEMPTS` with an UPSERT into a tiny `super_admin_throttle (ip PK, failures, window_start)` table.
- For a higher-volume audit, partition `super_admin_audit` by month and keep the index on `ts DESC`.

## Cross-references
- `03-admin-gate.md` — the base admin session this layer sits on top of. The lock hook runs after `@admin_required`.
- `02-multi-tenant-scaffolding.md` — `/admin/api/tenant/features` is one of the four protected prefixes; flag flips are exactly what this audit log is designed to catch.
- `01-fernet-secret-encryption.md` — the secrets editor (also protected) is the front door for the values this skill encrypts.
