# Replit OAuth Bridge ("Log in with Replit")

One-line: Wire the Replit-managed "Log in with Replit" integration into a Flask app as a future identity entry point. The integration is **installed** in this template (`javascript_log_in_with_replit:2.0.0`) but is **not yet wired into the live admin gate** — this blueprint describes the slot it occupies and how to graft it on without disturbing the shared-password gate.

Category: Auth & Multi-tenancy

## When to use
- You are running on Replit (workspace or deployment) and want visitors to sign in with their Replit account so you can attribute orders, RSVPs, chat sessions, or saved pages to a real identity.
- You want an admin "Sign in as me" shortcut for the workspace owner without typing the shared admin password.
- You want OIDC identity without operating your own OAuth provider.

Do NOT use this when:
- You will deploy off-Replit. The integration assumes the Replit runtime injects `REPL_IDENTITY` / `REPLIT_CONNECTORS_HOSTNAME`.
- You need verified email or domain restrictions Replit OAuth does not enforce.

## Architecture (target shape)
1. The integration is listed in `.replit` under `integrations`. Replit's runtime injects:
   - `REPL_IDENTITY` — short-lived identity token, refreshed by `WEB_REPL_RENEWAL`.
   - `REPLIT_CONNECTORS_HOSTNAME` — broker hostname for connector API calls.
   - `REPLIT_DOMAINS` — comma-separated list of authorized hostnames.
2. The bridge exposes two routes:
   - `GET /auth/replit/login` — redirect into Replit's authorize URL with `state` (CSRF) and `redirect_uri` set to `/auth/replit/callback`.
   - `GET /auth/replit/callback` — verify `state`, exchange the code at the connector broker, fetch the user profile (`{ id, name, email?, profile_image? }`), upsert into a local `users` table, and set `session["replit_user_id"] = …`.
3. The same `@admin_required` decorator (skill `03-admin-gate.md`) is augmented to also accept `session["replit_user_id"]` when that user's row carries `is_admin = TRUE`.
4. `ProxyFix` (already mounted) makes the callback's absolute `redirect_uri` come out as `https://…` so Replit's OAuth checks pass.
5. The `REPLIT_DEPLOYMENT` env var (auto-set in production) flips `SESSION_COOKIE_SECURE=True`, which OAuth requires.

## Data model (suggested)
```sql
CREATE TABLE users (
  id              SERIAL PRIMARY KEY,
  tenant_id       INTEGER NOT NULL DEFAULT 1,
  replit_user_id  TEXT UNIQUE,           -- nullable for password-only users
  email           TEXT,
  display_name    TEXT,
  avatar_url      TEXT,
  is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMP DEFAULT NOW(),
  last_seen_at    TIMESTAMP
);
CREATE INDEX idx_users_tenant ON users (tenant_id);
```

Optional `auth_states (state PK, created_at)` table if you do not want to put the CSRF state in the session.

## API surface
- `GET /auth/replit/login?next=/admin` — kick off OAuth, store `state` + `next` in session.
- `GET /auth/replit/callback?code=…&state=…` — verify, upsert, set session, redirect to `next`.
- `POST /auth/replit/logout` — `session.pop("replit_user_id", None)`; leave the rest of the Flask session intact so non-admin features keep working.

## Key files in this codebase
- `.replit` — `integrations = [..., "javascript_log_in_with_replit:2.0.0", ...]` (installed only).
- `app.py` — `ProxyFix` setup and `SESSION_COOKIE_SECURE` logic already exist (~lines 130–340). These are the prerequisites for adding the bridge.
- `app.py` — `admin_required` decorator (~line 5199) is the extension point.
- `stripe_client.py` / `messaging.py` already show the pattern for reading `REPL_IDENTITY` and talking to the connectors broker; reuse their HTTP shape.

## External dependencies
- Replit's "Log in with Replit" integration (declared in `.replit`).
- `httpx` (already a dep) for the token-exchange call.
- No new Python packages.

## Pitfalls
- **Not wired into the live admin gate today.** Treat any blueprint code as new feature work, not a refactor. The existing shared-password gate keeps working untouched.
- **Two session keys, two logouts.** If both gates coexist, decide explicitly whether `/admin/logout` should also clear `replit_user_id`. The current `admin_logout` only pops `admin_logged_in`, `_csrf_token`, `super_admin_unlocked_at`.
- **Off-platform deploys break silently.** Without `REPL_IDENTITY` injection the broker call returns 401 and the callback returns 500. Detect with `env_manager.is_replit_platform()` and render a friendlier fallback.
- **State must round-trip via the session.** Storing state in a URL or cookie alone makes it forgeable. Use `secrets.token_urlsafe(32)` and `session["_oauth_state"]`.
- **Redirect-URI scheme.** Without `ProxyFix` (already mounted here), `url_for('replit_callback', _external=True)` returns `http://…` and the OAuth handshake fails. Verify this when porting.
- **Linking accounts.** First login lands as a new row even if an `email` matches an existing admin. Decide upfront whether email auto-links and how to handle conflicts (the safe default is to refuse and force a manual link from the admin panel).
- **Token TTL is short.** `REPL_IDENTITY` rotates; do not cache the token across requests — re-read from `os.environ` per call.

## Adaptation notes
- For a non-Replit clone, swap this for "Sign in with Google" using `authlib` — the route shape (`/auth/<provider>/login`, `/auth/<provider>/callback`) and the `users` table stay identical.
- Layer onto skill `03-admin-gate.md`: leave the shared password as a break-glass option, add the OAuth bridge as the preferred path, and use `users.is_admin` to gate admin features. Keep `super_admin_unlocked_at` (skill `04`) independent so OAuth identity does not weaken the second-factor.
- For multi-tenant: extend `users` with `tenant_id`, resolve the active tenant from the host/subdomain at callback time, and store it in the session so `current_tenant_id()` (skill `02`) can return it.
- Stash the user record in `g` from a `before_request` hook so view code can read `g.user.email` without re-querying.

## Cross-references
- `03-admin-gate.md` — the gate this bridge extends, not replaces.
- `02-multi-tenant-scaffolding.md` — `users.tenant_id` plus the resolved-at-login tenant id is the natural place to flip `current_tenant_id()` from a constant to a lookup.
- `04-super-admin-audit.md` — the second-factor stays orthogonal; OAuth identity does not unlock the secrets editor.
