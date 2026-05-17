# Env Manager + In-App Secrets UI (Host-Wins With Per-Key Override)

## When to use
You ship a self-hostable app with a long list of integration credentials (Stripe, Twilio, Resend, OpenAI, …) and you want the admin to manage them from a tab in the UI without (a) leaking secrets to the database, (b) shadowing platform-managed secrets (Replit Secrets, Docker `-e`, systemd `EnvironmentFile=`), or (c) letting the admin set arbitrary process-wide env vars by name.

## Architecture
Three rules, ranked by priority:

1. **Whitelist or reject.** A curated `KNOWN_VARS` list declares every variable the app cares about — name, category, level (required/recommended/optional), one-line description, `sensitive` flag (mask when displaying), `restart` flag (does a change need a workflow restart to take effect). Writes to unknown keys are rejected.

2. **Host always wins (by default).** At process start, `load_env_file_into_environ()` parses the local `.env` file and copies each value into `os.environ` *only if the key is not already set*. Platform-managed secrets keep precedence; `.env` is a dev-only / missing-secret fallback. A module-level `_env_file_keys` set tracks which keys were actually applied (i.e. weren't shadowed) — used later to classify each var's effective source as `env_file` vs `replit_secret` vs `unset`.

3. **Per-key override opt-out.** Sometimes the admin DOES want the .env value to win — e.g. a wrong prod secret needs hot-patching. `set_var(key, value, force_override=True)` writes the key, adds it to the sibling `.env.overrides` flag file (plain text, one key per line), snapshots the host's current value in memory, and on the next loader pass that .env value is forced into `os.environ` even if the host had its own. Clearing the override removes the .env entry, drops the flag, and restores the host value.

Two further safety properties:
- **Sensitive values are never echoed in clear.** Anything matching `KEY/SECRET/PASSWORD/TOKEN/SID/DSN`, plus `DATABASE_URL`, masks to `••••XXXX` (last 4 chars). The API surface for displaying status never returns plaintext for sensitive keys.
- **Atomic `.env` writes.** `tempfile.mkstemp` + `os.chmod(0600)` + `os.replace` — a crash mid-write can never leave a half-written file. Same pattern for `.env.overrides`.

The `.env` parser tolerates `export KEY=val`, double-quoted with escapes (`\n`, `\"`, `\\`), single-quoted (raw), and bare values, and silently skips malformed lines (the file is admin-edited, never crash on a typo).

## Data model
None. State lives in:
- `os.environ` (runtime values).
- `.env` (persisted values; gitignored; mode 0600).
- `.env.overrides` (plain-text key list; gitignored).
- In-memory `_env_file_keys: set`, `_overrides: set`, `_host_shadowed_values: dict` (rebuilt on every loader call).

## API surface
- `load_env_file_into_environ(path=None) -> int` — call once at app boot.
- `get_status() -> list[dict]` — for the admin UI; returns per-key rows with masking applied.
- `set_var(key, value, force_override=False)` — write + (optionally) flag for override.
- `unset_var(key)` — remove from .env and clear any override; restores the host snapshot.
- `is_replit_platform() -> bool` — UX hint for labeling "Replit Secret" vs "Environment Variable" in the UI.

## Key files
- `env_manager.py` — entire implementation.
- `app.py` — imports `env_manager` and calls `load_env_file_into_environ()` *before* anything else reads from the environment.

## External deps
Standard library only (`os`, `re`, `tempfile`). No `python-dotenv` — the parser is hand-rolled to (a) get the host-wins semantics right, (b) avoid a runtime dep for a 200-line task.

## Pitfalls
- **Order matters at boot.** Load the .env file BEFORE you import any module that reads `os.environ` at import time (Sentry, OpenAI, Stripe). One late import shadows everything.
- **Override snapshots are in-memory only.** A restart rebuilds them from whatever the host currently has — fine, but if the host changes its value between override-set and restart, the "restore" target moves too. Document it.
- **`restart=True` keys** (FLASK_SECRET_KEY, DATABASE_URL, SENTRY_DSN, …) won't visibly change behavior until the workflow restarts. The UI must surface that explicitly or admins will think the save didn't work.
- **Whitelist drift.** Every new integration must add its key to `KNOWN_VARS` or the admin can't save it. Treat as part of "adding a new integration" checklist.
- **`.env` must be gitignored.** Always. Ship a `.env.example` instead with empty values.
- **Don't echo back full sensitive values** in any error message or log line — the masking layer is the only place plaintext should appear, and only for non-sensitive keys.

## Adaptation notes
- The pattern works on any host: Heroku Config Vars, Docker `-e`, systemd `EnvironmentFile=`, Kubernetes Secrets, AWS Parameter Store (with a thin loader). The "host wins" rule is what makes it host-agnostic.
- For multi-process deployments, on-disk `.env` writes are visible to all workers on the same node only after they restart (or call `load_env_file_into_environ` again). Don't expect live propagation.
- If you grow beyond ~100 vars, group `KNOWN_VARS` into category modules and import-aggregate.

## Adoption checklist
- [ ] Curate `KNOWN_VARS` from your `.env.example`. Tag `sensitive`, `restart`, `level`, `category`.
- [ ] Lift the `.env` parser + atomic writer.
- [ ] Call `load_env_file_into_environ()` as the *first* import-time side effect in your app entry point.
- [ ] Implement the override flag file with the same atomic-write pattern.
- [ ] Build the admin UI from `get_status()` — mask sensitive values, label source (env_file / platform / unset).
- [ ] Add a "Save & restart" button for `restart=True` vars (or just label them clearly).
- [ ] Gitignore `.env` and `.env.overrides`. Ship `.env.example` with empty values.
- [ ] Audit every existing call site that reads sensitive env vars at import time — those need to happen AFTER the loader runs.
