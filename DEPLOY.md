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

After your first successful boot, confirm:

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
