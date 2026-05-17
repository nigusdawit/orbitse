# Password-Protected Admin Gate

One-line: A single shared-password admin login backed by Flask sessions, an `@admin_required` decorator that returns 302 to humans and JSON 401 to fetch clients, and an in-process per-IP brute-force throttle.

Category: Auth & Multi-tenancy

## When to use
- You are protecting a single operator dashboard, not a multi-user SaaS with per-user accounts.
- You want zero external dependencies — no Auth0, no Cognito, no `flask-login`.
- You want the dashboard JS to recognize "session expired" cleanly instead of silently following a redirect to the HTML login page.

Do NOT use this when:
- You need per-user identity, audit-by-user, or role-based access control. Reach for a real auth library and a `users` table.
- You need SSO. Bolt the gate onto the SSO callback instead.

## Architecture
1. `ADMIN_PASSWORD` env var holds the single shared secret. Default `"admin"` for first-boot only.
2. `/admin/login` (GET → form, POST → verify) compares the submitted password with constant-time equality, sets `session["admin_logged_in"] = True`, marks `session.permanent = True`, and redirects to `/admin`.
3. `/admin/logout` pops the admin flag and any related session keys (CSRF token, super-admin unlock timestamp) and bounces to the login form.
4. `@admin_required` wraps every protected route. If unauthenticated:
   - **HTML routes** → 302 redirect to `/admin/login`.
   - **JSON / XHR / `/admin/api/*`** → JSON 401 `{ "error": "...", "auth_required": true }`. This is the critical bit: the dashboard JS would otherwise silently follow the redirect and show "Could not save settings" on session expiry.
5. **Brute-force throttle.** A module-level `dict` keyed by `request.remote_addr` tracks failed-attempt timestamps inside a sliding window (default 5 fails / 15 min). When the window is full, POSTs return HTTP 429 with `Retry-After`. A successful login clears the IP's entry.
6. **Session cookie hardening.** `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `PERMANENT_SESSION_LIFETIME=30 days`, and `SESSION_COOKIE_SECURE` flipped on whenever `FORCE_SECURE_COOKIES` or `REPLIT_DEPLOYMENT` is set.
7. **Session secret persistence.** `app.secret_key` resolves to (in order): `FLASK_SECRET_KEY` env, a persisted `.flask_secret` file (chmod 600), or a fresh `secrets.token_hex(32)` written to that file. This stops every workflow restart from logging admins out.
8. **`ProxyFix` is mounted** (`x_proto=1, x_host=1, x_for=1`) so `request.remote_addr` reflects the real client behind the platform's edge proxy and OAuth/Stripe absolute URLs come out as https.

## Data model
None. State lives in the signed Flask session cookie plus the in-process throttle dict.

## API surface
- `GET /admin/login` — render form.
- `POST /admin/login` — `password=…`. Returns 200 (form re-rendered with error), 302 (success), or 429 (throttled).
- `GET /admin/logout` — clears session, 302 to login.
- Decorator `admin_required(f)` — apply to every admin route and every `/admin/api/*` endpoint.

## Key files in this codebase
- `app.py` — config (`SESSION_COOKIE_*`, `PERMANENT_SESSION_LIFETIME`, `ProxyFix`, `_resolve_flask_secret`) (~lines 130–340).
- `app.py` — throttle dict + helpers `_login_throttle_check/record_failure/clear` (~lines 340–395).
- `app.py` — `admin_required`, `admin_login`, `admin_logout` (~lines 5190–5275).
- `templates/admin/login.html` — the form.

## External dependencies
- Flask sessions (built-in).
- `werkzeug.middleware.proxy_fix.ProxyFix`.
- Python stdlib only for the throttle (no Redis).

## Pitfalls
- **Default password "admin".** The code falls back to it if the env var is unset. Ship an init step that refuses to start without an explicit, non-default value.
- **In-process throttle resets on restart.** A determined attacker can trigger restarts to clear counters. Acceptable for shared-password admin; move to Postgres or Redis if you scale workers horizontally.
- **`request.remote_addr` only as trustworthy as `ProxyFix` is configured.** If you put the app behind a second proxy or self-host without setting `X-Forwarded-For`, every client collapses to one IP and the throttle becomes a global rate limit.
- **Constant-time compare is not used today.** Password equality is a plain `==`, which leaks timing on a long compare. Move to `secrets.compare_digest` if the password might be long enough to matter.
- **Session secret rotation logs everyone out** and also breaks `decrypt_secret` (see `01-fernet-secret-encryption.md`). Plan rotations together.
- **No CSRF on the login form itself.** The session is empty before login; the dashboard CSRF token is minted post-login.
- **No per-user audit trail.** One admin = one session. If you need to know "who logged in when," extend `admin_login` to write a row keyed by IP/UA before flipping into multi-user.

## Adaptation notes
- To add a second admin: keep this shape, swap the env var for a `users(email, password_hash)` table and `bcrypt.checkpw`. The decorator only changes from `session.get("admin_logged_in")` to `session.get("user_id")`.
- To bolt SSO on: keep the decorator, replace the login route with an OAuth callback that sets the same session key.
- To survive multi-worker deployments: persist the secret to a shared store (KMS, env), and move the throttle to Postgres (`INSERT ... ON CONFLICT DO UPDATE SET attempts = attempts + 1, last_at = NOW()`).
- The "JSON 401 vs HTML 302" branch is the single most useful pattern here for any app whose admin UI uses `fetch` heavily.

## Cross-references
- `02-multi-tenant-scaffolding.md` — store the resolved `tenant_id` in the admin session at login.
- `04-super-admin-audit.md` — the optional second-factor key that gates the most dangerous admin tabs.
- `05-replit-oauth-bridge.md` — alternative entry point when integrating with the Replit OAuth integration.
