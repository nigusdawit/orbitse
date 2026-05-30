# Deploying admin_ai_platform (M20)

The platform ships as **one container image, identical for every install**. All
per-client behavior is data (env + database), so the same image runs every silo
client — see `tasks/022-fleet-sync.md` for the master→fleet update story.

Gunicorn entry point is the app factory: **`admin_ai_platform:create_app()`**.

---

## 1. Docker (any host)

```bash
cp .env.example .env          # fill in DATABASE_URL, ADMIN_PASSWORD, a provider key
docker build -t ai-concierge .
docker run --env-file .env -p 5000:5000 ai-concierge
# → http://localhost:5000   (first run: /setup, then /admin)
```

## 2. Docker Compose (app + pgvector Postgres + Redis)

```bash
cp .env.example .env
docker compose up --build
```

Compose brings up a `pgvector/pgvector:pg16` Postgres (RAG works out of the box)
and an optional Redis for the shared rate limiter. For production, point
`DATABASE_URL` at a managed Postgres and drop the `db` service.

## 3. Railway

- New Project → Deploy from repo. Railway reads `railway.json` (Dockerfile build,
  `/healthz` check).
- Add a **Postgres** plugin; Railway injects `DATABASE_URL`.
- Set variables: `ADMIN_PASSWORD`, a provider key (`OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY`), `FLASK_SECRET_KEY`, `SECRETS_ENCRYPTION_KEY`,
  `DEPLOY_MODE=self_host`, `SESSION_COOKIE_SECURE=true`, `TRUSTED_PROXY_HOPS=1`.
- Enable the `vector` extension on the DB for RAG: `CREATE EXTENSION IF NOT EXISTS vector;`

## 4. Render

- New → **Blueprint**, point at `render.yaml`. It provisions the web service +
  a Postgres and generates `FLASK_SECRET_KEY`/`SECRETS_ENCRYPTION_KEY`.
- Set the `sync: false` secrets (`ADMIN_PASSWORD`, provider keys) in the dashboard.
- Enable pgvector once: `CREATE EXTENSION IF NOT EXISTS vector;`

---

## System dependencies (already in the Docker image)

| Dependency | Why | Without it |
|---|---|---|
| **pgvector** (server extension) | RAG / knowledge base embeddings | KB tab disabled; app still boots |
| **LibreOffice** (`libreoffice-impress`) | Presentation import → PDF | import keeps text+notes, skips slide images |
| **poppler-utils** (`pdftoppm`) | PDF → per-slide JPGs | slide images skipped |
| **fonts-liberation / dejavu** | LibreOffice text rendering | blank/box-glyph deck images |

## Widget bundling

`python -m admin_ai_platform.bundle` concatenates + minifies the widget into
content-hashed files under `embed/dist/` (built automatically in the Docker
image). Served at:
- `/embed/dist/manifest.json` — `{version, js, css}` (short cache)
- `/embed/dist/widget.<hash>.js|.css` — immutable, `max-age=1y` (hash busts cache)

Set `WIDGET_CDN_BASE` if you serve the bundle from a CDN. For **silo**, prefer
serving per-instance (the bundle versions with the instance), so an out-of-date
client's widget can't break against a newer API.

## Migrations policy (additive-only)

The package **self-bootstraps** its schema on every boot via `schema.init_db()`,
which is **idempotent and additive-only** (`CREATE TABLE IF NOT EXISTS`,
`ADD COLUMN IF NOT EXISTS`, sequence `setval`). This is what makes a master image
roll-out safe across the fleet: a new image's `init_db()` applies the new
columns/tables to each client DB on startup with no manual migration step.

Rules for any schema change (so rollouts never break a client):
- **Never** drop/rename a column or add `NOT NULL` without a default.
- Use the expand/contract pattern for transforms (add new → backfill → switch →
  later remove), so old code tolerates the new schema and rollback stays possible.

`alembic` is available (a dependency) if you later want versioned migrations;
`SKIP_ALEMBIC=true` is honored as a reserved flag for installs where external
tooling owns the schema. Today the additive `init_db()` is the migration.

## Snapshot / clone CLI

Bootstrap a new client install from a master template:

```bash
# On the master:
python -m admin_ai_platform.snapshot export master.json
# On the fresh client install (its own DATABASE_URL):
python -m admin_ai_platform.snapshot apply master.json
```

Exports template config (chatbot/provider/voice settings, gallery, forms,
presentations, skills, content) with **secrets redacted** — credentials are
provisioned per-instance and never travel in a clone.
