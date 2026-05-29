# Task 000 — M0: Scaffolding, shared infra & mode config

## Goal

Stand up the `admin_ai_platform/` package skeleton with the shared infrastructure carved out of
`app.py` as **independent copies** (DB pool, LLM clients, cost helpers), a config layer with the
`DEPLOY_MODE`/`ADMIN_MODE` flags and tenant resolution, a schema bootstrapper limited to the IN
tables, the Tier-1 helper modules relocated, the Tier-2 modules dependency-injected, and a
`create_app()` factory that boots cleanly in both deploy modes. No subsystem routes yet — this is the
foundation everything else builds on.

## Research block

- DB pool + `get_db/query_db/execute_db`: `app.py` ~603–862 (ThreadedConnectionPool, `_PooledConnection`).
- LLM clients: `app.py` ~548–595 (`openai_client` via proxy, `openai_direct_client`, `anthropic_client`,
  ElevenLabs key). `agent_provider_settings` table drives provider switch.
- Cost helpers: `record_chat_cost` and friends (grep in `app.py`); `cost.py` blueprint comes in M3 but
  the write helpers + `enforce_cost_cap`/`cost_cap_blocks_send` are needed package-wide → put in `cost.py`.
- `init_db()`: `app.py` ~1134–3915. Extract only IN tables (+ AI-read data tables). Keep `IF NOT EXISTS`.
- Tier-1 modules (move verbatim, fix imports to relative): messaging, automations, scraper, storage,
  image_optimize, asset_bundle, devconsole, stripe_client, velo_client, env_manager.
- Tier-2 modules (DI): rag, semantic_cache (already `init_module(...)`), stripe_sync, stripe_settings,
  velo_endpoints, velo_handlers — replace `from app import ...` with injected deps.
- Scheduler: `messaging.py` ~442–482 (`register_tick`, `start_scheduler`, 30s loop).
- `current_tenant_id()`: find in app.py; in `self_host` returns 1, in `central` resolves from request
  (embed key / admin session / tenant header).

## Acceptance criteria

- [ ] `admin_ai_platform/` package created with: `__init__.py` (`create_app`), `__main__.py`,
      `config.py`, `db.py`, `llm.py`, `cost.py`, `schema.py`, `scheduler.py`, `blueprints/` (empty
      `__init__` placeholder), `reused/`, `reused_di/`.
- [ ] `config.py` exposes `DEPLOY_MODE`, `ADMIN_MODE`, and all mode/distribution env flags with
      sensible defaults; everything configurable, no hardcoded literals in business logic.
- [ ] `db.py` provides `init_pool/get_db/query_db/execute_db` independent of `app.py` (no `import app`).
- [ ] `llm.py` provides client factories + `get_active_llm_provider()` reading `agent_provider_settings`.
- [ ] `cost.py` provides the cost-write + cap-enforce helpers used by other modules.
- [ ] `schema.py::init_db()` creates ONLY the IN tables; runs idempotently on an empty DB.
- [ ] Tier-1 modules importable from `reused/` with no `from app import`. Tier-2 modules in `reused_di/`
      take their deps via an init function called from `create_app()`.
- [ ] `create_app()` boots with `DEPLOY_MODE=self_host` AND `DEPLOY_MODE=central`; scheduler starts once.
- [ ] `python -m admin_ai_platform` serves a health route; no dangling `from app import` anywhere
      (grep proves it).

## Test requirements

- `tests/test_config.py` — mode flag parsing + defaults; `current_tenant_id()` returns 1 in self_host.
- `tests/test_schema.py` — `init_db()` idempotent (run twice, no error); creates a known IN table,
  does NOT create a known OUT-only table (e.g. `sphere_settings`). Uses a test DB or transaction.
- `tests/test_imports.py` — import every package module; assert no module does `import app` /
  `from app import`.
- Boot smoke documented in task notes (manual `python -m admin_ai_platform` in both modes).

## Dependencies
None.

## Can run in parallel with
None (foundation).

## Status
done

## Branch
task/000-scaffolding-shared-infra

## Commits
- (recorded at merge)

## Drift reason
Full Tier-1/Tier-2 helper-module relocation deferred to the consuming milestones
(M1/M3/M4/M5/M6) rather than done up front — keeps M0 a small, genuinely bootable
foundation and avoids carrying dead code. The mechanism (`reused/`, `reused_di/`,
`scheduler.py`) is in place now; modules land as each subsystem needs them.

## Notes
- Independent-copy decision honored: db/llm/cost/tenancy/schema are standalone; original `app.py`
  untouched. Verified by `test_imports.test_no_legacy_app_import`.
- Tenant resolution + feature flags landed in `tenancy.py` (foundation); the tenancy *admin UI* is M6.
- Cost warn-line email sender left unset (no-op) until messaging is relocated (M3/M5).
- **Verification gate (passed):**
  - Build/import: `create_app(init_schema=False)` boots; `/healthz` 200. ✅
  - Lint: `ruff check admin_ai_platform/` → All checks passed. ✅
  - Tests: `pytest admin_ai_platform/tests/` → 8 passed, 2 skipped. ✅
  - New tests: test_config, test_imports, test_schema. ✅
  - Smoke: boots in DEPLOY_MODE=self_host AND central. ✅
  - Typecheck: N/A — no mypy configured for this project.
  - DB schema test: SKIPPED — no local Postgres (DATABASE_URL unset). Honest skip; runs in any
    env with a DB. Re-run with DATABASE_URL set to exercise init_db idempotency + IN/OUT assertions.
- Toolchain: project uses `uv` (uv.lock). Run tests via `uv run python -m pytest admin_ai_platform/tests/`.
