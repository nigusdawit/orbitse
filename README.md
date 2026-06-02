# AI Concierge Platform

A Python + Flask web application for small businesses (restaurants, hotels,
service providers) that bundles a public website, an AI chatbot concierge,
a storefront with Stripe checkout, an admin panel, and an optional
integration with VELO Master for centralized multi‑install management.

> **For developers / operators only.** End users (restaurant staff, etc.)
> never see this file — they only see the admin panel at `/admin`.

---

## Quick start (local development)

You need **Python 3.11+** and a **Postgres database** reachable on the network.

```bash
# 1. Clone the repo
git clone <your-repo-url> ai-concierge
cd ai-concierge

# 2. Install Python dependencies
pip install -r requirements.in
# (or, if you use uv: `uv sync`)

# 3. Set up environment
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL, ADMIN_PASSWORD, and one of
# OPENAI_API_KEY / ANTHROPIC_API_KEY

# 4. Start the app
python app.py
# Production: gunicorn --bind 0.0.0.0:5000 --workers 4 app:app

# 5. Verify the install is healthy
python scripts/preflight.py
# Reports ✅/⚠️/❌ for required env vars, schema state, and each
# optional integration. Exit 0 = healthy, 1 = required check failed.

# 6. Run the first-run wizard
#   Visit http://localhost:5000/setup, pick a preset (generic or
#   restaurant), fill in your business name, paste your admin password,
#   and submit. The wizard provisions site settings, FAQs, services,
#   feature plan, and the admin user in one shot. After it completes
#   /setup auto-closes (returns 404 to anyone else).

# 7. Visit
#   Public site:  http://localhost:5000
#   Admin panel:  http://localhost:5000/admin
#                 (log in with whatever you set ADMIN_PASSWORD to)
```

The schema bootstraps itself on first boot — every `CREATE TABLE` and column
migration runs as `IF NOT EXISTS`, so pointing the app at an empty Postgres
database is enough.

### Cloning a working install to a new client

Once you have one client tuned the way you like, snapshot it and use that
JSON as the starting point for every subsequent client:

```bash
# On the source install (the dialled-in client):
python scripts/snapshot.py --pretty -o my-baseline.json

# Move my-baseline.json to the new client's environment, then POST it
# to /api/velo/command with command=bootstrap_install — see
# DEPLOY.md → "Cloning an existing install" for the full recipe and
# the per-section re-apply behavior.
```

The snapshot includes settings, feature flags, and FAQs by default.
Pass `--include-content` to also clone services and team profiles, or
`--include-all-content` for every content type. Customer/order/chat-history
rows are never included — those are runtime data, not template data.

For agencies running a master install whose **admin-side** config (agent
skills, MCP servers, dashboards, automations, messaging templates, model
prices, AI provider settings) should flow to every client, pass
`--include-admin`. Records are UPSERTed by name on re-apply, so re-pushing
the same snapshot updates clients in place instead of erroring on
duplicates. Sensitive columns (MCP credentials, automation webhook tokens)
are redacted by default; opt in with `--include-admin-secrets` if you
really do want to clone credentials too. See DEPLOY.md for the full
admin-clone recipe.

---

## One‑command Docker spin‑up

```bash
cp .env.example .env       # edit as needed
docker compose up --build  # app + Postgres come up together
```

App: <http://localhost:5000>. Postgres is reachable on host port `55432` for
debugging.

---

## Required vs optional configuration

The full inventory lives in `.env.example`. The short version:

| Tier | Variables | What happens if missing |
| --- | --- | --- |
| **Required** | `DATABASE_URL`, `ADMIN_PASSWORD`, one of `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | App won't boot or chatbot won't respond |
| **Strongly recommended** | `FLASK_SECRET_KEY`, `PUBLIC_BASE_URL`, `FORCE_SECURE_COOKIES`, `ADMIN_EMAIL` | Sessions don't survive restart, links break, no admin alerts |
| **Optional features** | Resend, Twilio, Stripe, ElevenLabs, Brave Search, Google/Yelp/TripAdvisor, Sentry, VELO | The corresponding feature turns off cleanly |

The app fails *open* on optional integrations — if a key is missing, the
feature it powers is disabled silently rather than crashing the boot.

The admin password defaults to literally `admin` if `ADMIN_PASSWORD` is unset.
**Always override it for any non‑local install.** The app prints a loud
warning at startup when this default is in effect.

---

## Project layout

```
app.py                    Slim Flask aggregator — imports, re-exports moved
                          symbols, blueprint registration, the global
                          before_request hooks, VELO wiring, __main__. Still
                          holds the schema bootstrap (init_db) and the bulk of
                          the AI/business logic not yet carved out (~40k lines)
core.py                   Shared infrastructure the blueprints import (the Flask
                          app + extensions, DB helpers, auth gates, feature
                          flags, prompts, AI-Control settings, cost infra)
admin/                    15 Flask blueprints — the feature routes split out of
                          app.py (public_api, content, forms, commerce, …)
velo_endpoints.py         /api/velo/command surface for VELO Master
velo_handlers.py          The 30 registered command handlers
messaging.py              Resend (email) + Twilio (SMS) wrappers
stripe_client.py          Stripe checkout & webhook handling
templates/                Jinja2 templates for the public site & admin panel.
                          The admin dashboard is a slim shell + ~65 per-tab
                          partials under templates/admin/tabs/
public/admin/             Extracted admin CSS/JS assets (no build step)
static/                   CSS, JS, images
uploads/                  User-uploaded media (PERSIST in production)
attached_assets/          Sample assets (safe to delete)
pyproject.toml            Source of truth for Python dependencies
requirements.in           Mirror for non-uv tooling (Docker, buildpacks)
Dockerfile                Production container image
docker-compose.yml        Local one-command spin-up
DEPLOY.md                 Per-platform deployment recipes
.env.example              Full environment-variable inventory
replit.md                 Agent-facing engineering notes
GUIDE.md                  Internal feature reference
AGENT_KNOWLEDGE_BASE.md   Internal knowledge base
```

---

## Deploying

See **`DEPLOY.md`** for step‑by‑step recipes for Render, Fly.io, Railway,
and a plain VPS.

If you're operating multiple installs and want them centrally manageable,
read the "VELO Master AI Integration" section of `replit.md` for how the
`/api/velo/command` surface lets a master server drive 30 operations on
each install over HTTP.

---

## License

Proprietary — all rights reserved.
