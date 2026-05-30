# Task 020 — M20: deploy artifacts + widget bundling + migrations + snapshot CLI

## Goal
Make the package independently deployable and the widget production-served.

## Acceptance criteria
- [x] Package deploy artifacts: `Dockerfile` fixed to the package factory
      (`gunicorn 'admin_ai_platform:create_app()'`, poppler-utils added),
      `docker-compose.yml` (app + pgvector Postgres + Redis), `requirements.txt`,
      `.env.example` (every config name, no values), and **Railway** (`railway.json`)
      + **Render** (`render.yaml`) recipes on top of Docker/compose.
- [x] System deps documented/installed: pgvector (server ext), LibreOffice +
      poppler-utils (deck import), fonts — in the image + `admin_ai_platform/DEPLOY.md`.
- [x] Widget bundling: `python -m admin_ai_platform.bundle` concats + minifies
      (rjsmin) the widget into content-hashed `embed/dist/widget.<hash>.{js,css}` +
      `manifest.json`; served immutable 1y (hashed) / short-cache (manifest);
      `WIDGET_CDN_BASE` honored; cache-busts on source change.
- [x] Migrations: documented the **additive-only `init_db()` policy** (idempotent
      CREATE/ALTER + sequence setval; expand/contract for transforms); `alembic`
      available + `SKIP_ALEMBIC` reserved/honored.
- [x] Snapshot/clone: `admin_ai_platform.snapshot` export/apply CLI (singletons +
      slug/name upserts + append-if-empty) with **provider-secret redaction**.

## Test requirements
- Boot from the Docker image against compose Postgres; `/healthz` 200; schema
  bootstraps. Bundle served with correct content-type + cache headers. Snapshot
  CLI round-trips (export → fresh DB → apply → rows present).

## Dependencies: none (can run parallel)   ## Status: done   ## Branch: task/020-deploy-and-assets

## Notes
Merged to main (--no-ff). Gate: 352/352 incl. widget bundle build (deterministic
hash) + served-immutable + manifest short-cache + path-traversal reject; snapshot
export→wipe→apply round-trip (gallery slug-upsert + business_info singleton +
idempotent re-apply + provider-secret redaction); and a check that .env.example
lists every config var name. Unit: `test_deploy.py` pins the snapshot row
coercion (_jsonable temporal/Decimal, _insert_cols identity-skip + jsonb-encode).
Drift: package DEPLOY.md written at `admin_ai_platform/DEPLOY.md` (root DEPLOY.md
is the monolith's, left untouched). Docker image build + live /healthz boot is
NOT runnable in the sandbox (no Docker) → that part verified by construction;
real container boot is part of M21. Fixed a stray null byte that slipped into
bundle.py's hash separator.
