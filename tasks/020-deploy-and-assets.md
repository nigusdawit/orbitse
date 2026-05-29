# Task 020 — M20: deploy artifacts + widget bundling + migrations + snapshot CLI

## Goal
Make the package independently deployable and the widget production-served.

## Acceptance criteria
- [ ] Package deploy artifacts: `Dockerfile` (gunicorn entry
      `admin_ai_platform:create_app()`), `docker-compose.yml` (app + Postgres +
      optional pgvector image + Redis), `pyproject.toml`/`requirements.txt` for
      the package, `.env.example` (every config name, no values), and recipes for
      **Railway** + **Render** (both confirmed) on top of Docker/compose.
- [ ] System deps documented/installed for full features: pgvector, LibreOffice
      (deck import), fonts.
- [ ] Widget bundling: concat (+ optional minify) chat-ui.css/js + voice.js into
      a versioned `embed/` bundle; cache headers + `WIDGET_CDN_BASE`; cache-bust
      on version change.
- [ ] Migrations: adopt Alembic for the package (or document the additive-only
      `schema.py` policy) so prod upgrades are safe; `SKIP_ALEMBIC` honored.
- [ ] Snapshot/clone completeness: more tables + admin-config + secret redaction;
      a `snapshot.py` CLI (export/apply) mirroring the original.

## Test requirements
- Boot from the Docker image against compose Postgres; `/healthz` 200; schema
  bootstraps. Bundle served with correct content-type + cache headers. Snapshot
  CLI round-trips (export → fresh DB → apply → rows present).

## Dependencies: none (can run parallel)   ## Status: not_started   ## Branch: task/020-deploy-and-assets
