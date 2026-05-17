# Preflight Env / Health Checks

**Category:** Admin Tooling
**Related:** `admin-tooling/02-dev-console.md`

## When to use
Every deploy has the same recurring failure mode: a required env var
is missing, the DB migration didn't run, or the seeded admin row is
gone. A preflight CLI catches all three before a single user hits a
broken page. Run it in CI, in your container entrypoint, or manually
after pulling a branch.

## Architecture
- A standalone `scripts/preflight.py` script — runnable as
  `python scripts/preflight.py` with exit code 0 on green, non-zero on
  red. CI / Docker `HEALTHCHECK` / Replit deploy hooks can gate on it.
- Four check buckets:
  1. **Required env vars** — `DATABASE_URL`, `ADMIN_PASSWORD`,
     `FLASK_SECRET_KEY`. Missing → fatal.
  2. **Recommended env vars** — `OPENAI_API_KEY`, `RESEND_API_KEY`,
     `SENTRY_DSN`, etc. Missing → warn, don't fail.
  3. **Schema bootstrap** — `SELECT 1 FROM <key tables>` to prove
     `init_db()` ran. Missing → fatal.
  4. **Integration handshake** — optional cheap probe per provider
     (re-uses the same code paths as the dev console).
- Each check prints a colored OK/WARN/FAIL line so CI logs are
  scannable.
- The script is purely additive — adding a new required var is one
  line in the `REQUIRED` tuple.

## Key files
- `scripts/preflight.py`
- `scripts/preflight.py:109` — `check_required`
- `scripts/preflight.py:187` — `check_recommended`
- `scripts/preflight.py:256` — `check_schema`
- `scripts/preflight.py:384` — `check_integrations`

## Data model
None — purely operational.

## External deps
- Whatever your app already uses (`psycopg2`, `httpx`, ...).
- Optional: `rich` or plain ANSI codes for color.

## Pitfalls
- **Don't import your Flask app** at the top of the preflight — that
  triggers DB/connection setup on import and any preflight failure
  becomes a stacktrace instead of a clean message. Import lazily
  inside each check.
- **Recommended ≠ required.** Operators run with placeholder Twilio
  creds during development; the preflight must warn, not exit-code-1,
  or local dev becomes painful.
- **Don't perform writes** in any check. A preflight that creates rows
  is a preflight that pollutes prod.
- **Network timeouts** — wrap every provider probe in a short timeout
  (5–8s) so a single down provider can't hang a deploy.
- **Secret values** must never be printed, only their presence.

## Adoption checklist
1. Create `scripts/preflight.py` with `REQUIRED`, `RECOMMENDED` tuples.
2. Implement each `check_*` returning `(status, message)` tuples.
3. Set non-zero exit only on FAIL (required env, broken DB).
4. Wire into CI / `Dockerfile` `HEALTHCHECK` / Replit deploy step.
5. Document the expected output in the project README so operators
   recognise green-on-green.

## Adaptation notes
- For Kubernetes, run as an `initContainer` so the main pod doesn't
  start unless preflight passes.
- For multi-tenant SaaS, run per-tenant after deploy so the dashboard
  can show "12 of 50 tenants are missing Twilio creds".
- Expose the same checks via `/admin/api/preflight` for an in-browser
  "Run system check" button (this is essentially what the dev console
  is for live providers; preflight covers env + schema + boot order).
