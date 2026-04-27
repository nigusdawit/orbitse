# Deployment recipes

Step‑by‑step for getting the AI Concierge Platform onto the most common
hosting targets. Pick the one that matches your situation.

| Target | Difficulty | Cost (rough) | Best for |
| --- | --- | --- | --- |
| Replit Deploy | Trivial | $7+/mo | Existing Replit users, fastest path |
| Render | Easy | Free–$25/mo | Click-and-go, managed Postgres add-on |
| Fly.io | Medium | $5+/mo | Global regions, cheap, great for international |
| Railway | Easy | $5+/mo | Similar to Render, friendly CLI |
| Plain VPS | Hard | $4+/mo | Maximum control, lowest cost at scale |
| Docker (any host) | Medium | Varies | Portable across clouds |

In every case, the schema bootstraps itself on first boot — no migration
step is required. You point the app at an empty Postgres database, set
the env vars, and it builds 80+ tables and the column migrations on its
own.

---

## Replit Deploy (fastest)

1. Open the project in Replit.
2. Add your secrets via the **Secrets** sidebar (everything in `.env.example`
   that isn't blank in your install).
3. Click **Deploy** → choose **Reserved VM** or **Autoscale**.
4. Replit handles the rest (TLS, custom domains, healthchecks).

The app already binds `0.0.0.0:5000` and uses gunicorn under the hood, so
no config changes are needed.

---

## Render

Render is the easiest "click and go" path for a from‑scratch deploy.

1. **Create a Postgres database** in Render (Settings → New → PostgreSQL).
   Pick a region, copy the **Internal Database URL**.
2. **Create a Web Service** pointing at your Git repo:
   - Runtime: **Python 3.11**
   - Build command: `pip install -r requirements.in`
   - Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 4 --timeout 120 app:app`
3. **Add environment variables** in the service's Environment tab. Paste
   them from your filled-in `.env`. Set `DATABASE_URL` to the internal URL
   from step 1.
4. **Set `FORCE_SECURE_COOKIES=1`** (Render terminates TLS at the edge).
5. **Set `PUBLIC_BASE_URL`** to the URL Render gave you (or your custom
   domain).
6. Deploy. First boot takes 60–90s while the schema bootstraps.

**libreoffice for PPT export** is *not* installed by Render's Python
runtime. If you need the slide-deck export feature, switch to the Docker
path instead (next section) — Render supports Dockerfile deployments.

---

## Render via Docker (recommended if you need PPT export)

Same steps as above, but set the runtime to **Docker** and Render will
build the included `Dockerfile`. libreoffice ships in the image.

---

## Fly.io

```bash
# Install flyctl, then:
fly launch                        # detect Dockerfile, create app
fly postgres create               # provision a Postgres cluster
fly postgres attach <pg-app-name> # sets DATABASE_URL
fly secrets set ADMIN_PASSWORD=... OPENAI_API_KEY=... \
                FLASK_SECRET_KEY=$(openssl rand -hex 32) \
                FORCE_SECURE_COOKIES=1 PUBLIC_BASE_URL=https://your-app.fly.dev \
                # ...rest of your .env values
fly deploy
```

Fly will use the included `Dockerfile`. The first boot bootstraps the
schema. Subsequent deploys are quick because the dep layer caches.

For a custom domain: `fly certs add yourdomain.com`.

---

## Railway

Railway auto‑detects either `pyproject.toml` or the `Dockerfile`. The
Docker path is recommended (PPT export works).

1. **New Project → Deploy from GitHub repo**.
2. Railway adds a Postgres plugin in one click. The `DATABASE_URL`
   variable is wired in automatically.
3. **Add the rest of your variables** under the service's Variables tab.
   Set `PUBLIC_BASE_URL`, `FORCE_SECURE_COOKIES=1`, `ADMIN_PASSWORD`, and
   any feature keys you want active.
4. Deploy. The app comes up at `https://<project>.up.railway.app`.

---

## Plain VPS (DigitalOcean, Hetzner, Linode, etc.)

Targets a fresh Ubuntu 22.04 / 24.04 droplet.

```bash
# As root:
apt-get update
apt-get install -y python3.11 python3.11-venv python3-pip \
                    postgresql postgresql-contrib \
                    libreoffice-impress \
                    nginx certbot python3-certbot-nginx \
                    git
                    
# Postgres
sudo -u postgres createuser aiconcierge
sudo -u postgres createdb -O aiconcierge aiconcierge
sudo -u postgres psql -c "ALTER USER aiconcierge WITH ENCRYPTED PASSWORD 'CHANGE_ME';"

# App user
useradd -m -s /bin/bash app
su - app
git clone <your-repo-url> /home/app/ai-concierge
cd /home/app/ai-concierge
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.in

# Environment
cp .env.example .env
nano .env   # fill in DATABASE_URL=postgresql://aiconcierge:CHANGE_ME@localhost:5432/aiconcierge etc.
exit
```

Create `/etc/systemd/system/ai-concierge.service`:

```ini
[Unit]
Description=AI Concierge Platform
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=app
WorkingDirectory=/home/app/ai-concierge
EnvironmentFile=/home/app/ai-concierge/.env
ExecStart=/home/app/ai-concierge/.venv/bin/gunicorn \
    --bind 127.0.0.1:5000 --workers 4 --timeout 120 \
    --access-logfile - --error-logfile - app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable + start:

```bash
systemctl daemon-reload
systemctl enable --now ai-concierge
systemctl status ai-concierge   # verify it's running
```

Nginx reverse proxy at `/etc/nginx/sites-available/ai-concierge`:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Enable + TLS:

```bash
ln -s /etc/nginx/sites-available/ai-concierge /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d yourdomain.com
```

Set in `.env`:
- `PUBLIC_BASE_URL=https://yourdomain.com`
- `FORCE_SECURE_COOKIES=1`

Then `systemctl restart ai-concierge`.

---

## Docker on any other host

The included `Dockerfile` and `docker-compose.yml` work on any Docker
host (your laptop, an EC2 instance, a Kubernetes cluster, etc.).

Local one-command spin-up:

```bash
cp .env.example .env  # edit as needed
docker compose up --build
```

Production deploy on a Docker host:

```bash
docker build -t ai-concierge .
docker run -d --restart unless-stopped \
    --name ai-concierge \
    -p 5000:5000 \
    --env-file .env \
    -v ai_concierge_uploads:/app/uploads \
    ai-concierge
```

Put nginx (or the host's load balancer) in front for TLS.

---

## Post‑deploy checklist

After your first successful boot, run the preflight doctor — it does
most of the checking for you:

```bash
python scripts/preflight.py
# Or for CI / scripting:
python scripts/preflight.py --json | jq .summary
python scripts/preflight.py --strict   # exit 2 if any warnings
python scripts/preflight.py --quiet    # show only non-OK items
```

The doctor reports on:

- **Required env vars** (DATABASE_URL reachable, ADMIN_PASSWORD set
  and non-default, FLASK_SECRET_KEY, at least one AI provider key)
- **Strongly-recommended env vars** (PUBLIC_BASE_URL/SITE_URL, ADMIN_EMAIL)
- **Tuning env vars (Tier 7 — connection pool)**:
  - `DB_POOL_MIN` (default `1`) — pre-warmed conns kept alive in the pool.
  - `DB_POOL_MAX` (default `10`) — hard cap on pooled conns. Bursts above
    this cap fall back to a fresh direct `psycopg2.connect()` (with a
    stderr `[db pool] exhausted` warning) so traffic spikes degrade
    gracefully instead of hard-failing. For a single-worker debug server
    `10` is plenty; for a `gunicorn -w N` deploy set `DB_POOL_MAX` per
    worker so total open conns stay within your Postgres `max_connections`
    (cluster total ≤ `N × DB_POOL_MAX + headroom`).
- **CSRF protection (Tier 7 — automatic, no env vars)**: every
  state-changing request to `/admin/*` is now validated against a
  per-session CSRF token. The dashboard SPA picks the token up from a
  `<meta name="csrf-token">` tag and a `window.fetch` wrapper auto-injects
  it as the `X-CSRF-Token` header — no per-call-site changes needed. If
  you write your own admin tooling that POSTs to `/admin/api/*`, fetch
  the token from `GET /admin/api/csrf-token` and pass it back in the
  `X-CSRF-Token` header (or as a `csrf_token` form field). Public
  `/api/*` routes, VELO Bearer-auth endpoints, HMAC webhooks, the
  `/admin/login` POST, and the `/setup` wizard are all exempt.
- **Schema bootstrap state** (table count, first-run wizard marker,
  admin user count)
- **Optional integrations** (Resend, Twilio, Stripe, ElevenLabs, Brave,
  Google Places, Yelp, TripAdvisor, Sentry, VELO) and which feature each
  one enables
- **Replit-specific env vars** (only when running on Replit)

Exit codes: `0` = healthy, `1` = required check failed, `2` = `--strict`
mode hit a warning. Wire it into your deploy pipeline if you want the
build to fail on misconfig.

If the doctor reports `[WARN] Install state: install marker is NULL`,
visit `/setup` in the browser to run the first-run wizard — that
provisions site name, theme, admin user, and feature plan in one
submit. (See "First-run wizard" in `replit.md` for details.)

Manual spot-checks if you don't want to run the doctor:

1. **Admin login works** at `/admin` with the password you set.
2. **The startup log doesn't print** `WARNING: ADMIN_PASSWORD is at the
   default value 'admin'`.
3. **Schema bootstrap completed** (look for "Database schema verified" or
   absence of CREATE TABLE errors in the log).
4. **Optional features are wired** — `/admin` settings pages should show
   "configured" rather than "not configured" for whichever integrations
   you set keys for.
5. **VELO Master, if used** — visit `/api/velo/status` and confirm it
   reports `count: 30` registered commands.

---

## Cloning an existing install (snapshot → fresh deploy)

Once you have one client's install dialed in (settings, persona, plan,
FAQs, services, team page, etc.), you can snapshot it and use that JSON
as the baseline for every subsequent client. No manual re-entry.

**On the source install** (the working client):

```bash
# Settings + features + faqs only (the most portable shape):
python scripts/snapshot.py --pretty -o ~/clientA-template.json

# Include the operator-facing content too (services + team profiles):
python scripts/snapshot.py --pretty --include-content -o ~/clientA-full.json

# Or grab everything (all 10 content types — only do this if you really
# want to clone testimonials, blog posts, events, etc.):
python scripts/snapshot.py --pretty --include-all-content -o ~/clientA-full.json
```

**On the target install** (the new client), apply via the API:

POST the snapshot to `bootstrap_install` through `/api/velo/command`
(two-step confirm-token flow — see `replit.md` for details). Re-apply
behavior by section:

- **Settings**: `UPDATE`-style, fully idempotent.
- **Features**: `bulk_set`, fully idempotent (every feature flag in the
  snapshot is set to its captured value, regardless of prior state).
- **FAQs**: deduped on question text — re-running won't insert duplicates.
- **Content**: `INSERT`-style. Most content tables (`blog_posts`,
  `events`, `products`, `services`, `gallery_cards`, `page_sections`)
  have a `UNIQUE` constraint on `slug`, so re-applying a content section
  that already exists will fail with a duplicate-key error rather than
  silently duplicate. Only include content on a known-empty target, or
  delete the conflicting rows first.
- **Admin user**: only included if you passed `--include-admin-user`;
  on existing email it returns `existed: true` (no-op), otherwise it
  creates the customer row.

A future revision of the `/setup` wizard will accept a snapshot JSON
upload directly (no-code clone). For now, the API path above is the
one supported flow.

**What snapshots intentionally don't include**:

- `admin_user` (off by default — admin identity is per-install, not
  per-template; pass `--include-admin-user` if you really want to
  copy the operator's email/name across)
- Customer / order / chat-history rows (these are runtime data, never
  template data)
- Tenant-specific content (events, blog posts, testimonials, etc.) —
  opt in via `--include-content=blog,events,...`
- Auto-generated columns (`id`, `created_at`, `updated_at`) so the
  target install's sequences and uniqueness constraints stay clean

Exit codes: `0` = clean snapshot, `1` = couldn't connect to the DB,
`2` = partial snapshot (some sections failed but JSON was still written;
warnings on stderr).

### Cloning admin-side configuration (Tier 6)

Beyond the customer-facing settings/FAQs/content above, the snapshot tool
can also export your **admin-side** configuration — agent skills, MCP
servers, dashboards, automations, messaging templates, model prices, and
the AI provider/automation policy. This is the "agency master → all
clients" path: dial in a skill on the master install, snapshot, replay
on every client, and they all get the new skill (or the updated version
of an existing one).

```bash
# Master install — export admin config alongside customer config:
python scripts/snapshot.py --pretty --include-admin -o ~/master-admin.json

# If you also want MCP credentials and webhook tokens copied across
# (rarely the right call — clients usually need their own credentials):
python scripts/snapshot.py --pretty --include-admin --include-admin-secrets -o ~/master-full.json
```

What `--include-admin` adds to the snapshot:

- `settings.agent_provider_settings` and `settings.automation_settings`
  (singletons — folded into the existing `settings` block, applied via
  the same `update_settings` route).
- `admin_records.agent_skills`, `custom_sql_skills`, `custom_webhook_skills`,
  `mcp_servers`, `automations`, `messaging_templates`, `model_prices`.
  Multi-row tables, exported as full lists.
- `admin_records.dashboards` with each dashboard's `widgets` nested
  underneath (the `dashboard_id` foreign key is stripped on export and
  re-resolved by parent name on import, so dashboards survive moving
  across installs even though their `id` sequences differ).

**Re-apply behavior on the target install** (UPSERT-by-natural-key):

- `agent_skills`, `custom_sql_skills`, `custom_webhook_skills`,
  `mcp_servers`: keyed by `name` (UNIQUE-constrained). If a row with the
  same name exists, it's UPDATED in place. Otherwise INSERTed.
- `model_prices`: keyed by composite `(provider, model, surface)`.
- `dashboards`, `automations`, `messaging_templates`: keyed by `name`
  (no UNIQUE constraint at the DB level — the upsert uses
  `ORDER BY id ASC LIMIT 1` so on an install with duplicate-name rows
  the lowest-id row is the canonical one and gets updated; newer
  duplicates are left untouched).
- `dashboard_widgets`: keyed by composite `(dashboard_id, name)` —
  widget names are only unique within a dashboard, so the parent FK is
  part of the natural key. On import the `dashboard_id` is re-resolved
  from the parent dashboard's name (the FK is not carried in the
  snapshot file).
- The bootstrap summary returns per-table `{created, updated, skipped, errors}`
  counts plus nested per-child counts under `dashboards.widgets`.

**Sensitive-column redaction** (default behavior):

- `mcp_servers.auth_credential` and `mcp_servers.oauth_state` (OAuth
  tokens, basic-auth secrets) — **stripped** from the snapshot.
- `custom_webhook_skills.headers_json` (may contain auth headers) —
  **stripped** from the snapshot.
- `automations.webhook_token` (per-install secret used to authenticate
  inbound webhook calls) — **stripped** from the snapshot.

Pass `--include-admin-secrets` to keep them. The CLI rejects
`--include-admin-secrets` without `--include-admin` (exit 2) so a typo
can't accidentally produce a snapshot file you didn't mean to.

**Operational columns are always stripped** regardless of flags:
`created_at`, `updated_at`, `last_test_at`, `last_test_ok`,
`last_test_error`, `last_run_at`, `last_run_status`, `next_scheduled_at`.
These are per-install runtime state, not template content.

---

## Notes on legacy Replit-isms

A few things in the repo are leftovers from this app's Replit origins. None
of them break off‑Replit deployments, but here's what they are so you know
they're safe:

- **`stripe-replit-sync` in `package.json`** — a Node helper used only on
  Replit to keep Stripe webhooks in sync with the integration system. Not
  imported by any Python runtime code. Safe to leave in place; not
  installed by the Dockerfile.
- **`REPLIT_DOMAINS` env var** — auto-set on Replit hosts. Off‑Replit, set
  `PUBLIC_BASE_URL` instead — the app honors it as the canonical URL for
  unsubscribe links, webhook callbacks, and SEO canonical tags.
- **`REPLIT_DEPLOYMENT` env var** — auto-set on Replit deploys. Off‑Replit,
  set `FORCE_SECURE_COOKIES=1` instead to enable HTTPS-only session
  cookies. Behind any TLS-terminating proxy (nginx, Render, Fly, Railway),
  set this.
- **Replit Auth integration metadata** — referenced in some platform
  metadata files but not used at runtime. Ignore off‑Replit.

---

## Upgrading

The app handles its own schema migrations on every boot via `CREATE TABLE
IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`. To upgrade an install:

1. Pull the new code.
2. Restart the app process (or rebuild + redeploy the container).

That's it — no migration step.
