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
app.py                    Single-file Flask application (routes, schema,
                          business logic) — currently ~31k lines
velo_endpoints.py         /api/velo/command surface for VELO Master
velo_handlers.py          The 30 registered command handlers
messaging.py              Resend (email) + Twilio (SMS) wrappers
stripe_client.py          Stripe checkout & webhook handling
templates/                Jinja2 templates for the public site & admin panel
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
