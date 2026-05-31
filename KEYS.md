# KEYS.md — where every key lives & how to provision a client install

This is the operator's reference for **secrets and keys** in the AI Concierge
platform (the `app.py` product). It lists every key, **where it's stored**, whether
it's **required**, and the per-install setup. Env-var names below are the real ones
the code reads (verified against `app.py`, `stripe_client.py`, `messaging.py`).

## Mental model (read this first)

- **Secret keys live in server environment variables** — never in the database,
  never sent to the browser. (OpenAI, Stripe, Twilio, etc.)
- **The only key that ever reaches the client/browser is the publishable embed
  key** (`pk_...`). It's *not* secret; it's protected by an **origin allowlist**.
- **Secrets the app must store in the DB** (e.g. an MCP server's bearer token) are
  **Fernet-encrypted at rest**, with the encryption key derived from
  `FLASK_SECRET_KEY`.
- **Silo model:** one install + one DB per client, so **each client install has its
  own env vars**. Provisioning a client = setting that install's env.

Env vars can be set three ways (any works): the host's environment, a **`.env`
file** in the app dir (loaded on boot by `env_manager`), or the admin **Secrets
tab** (`/admin/api/secrets/set`) at runtime.

---

## 1. REQUIRED — the install won't work without these

| Env var | What | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | App auto-creates all tables on first boot. Needs the `vector` extension for RAG. |
| `FLASK_SECRET_KEY` | Signs session cookies **and** derives the at-rest encryption key for DB secrets | **Set this explicitly in prod.** Fallback is a `.flask_secret` file, else a random key — and if it changes, encrypted DB secrets become undecryptable (see §6). |
| `ADMIN_PASSWORD` | Admin panel password | **Defaults to `admin` if unset** — boot warns about it. Always override. |
| At least one LLM key (below) | The chatbot needs a provider | `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. |

## 2. AI providers (at least one required)

| Env var | Feature |
|---|---|
| `OPENAI_API_KEY` | Chat, embeddings (RAG), Whisper STT, TTS |
| `AI_INTEGRATIONS_OPENAI_API_KEY` / `AI_INTEGRATIONS_OPENAI_BASE_URL` | Optional OpenAI-compatible proxy (overrides the direct key for chat) |
| `ANTHROPIC_API_KEY` | Claude provider + Anthropic web search |
| `ELEVENLABS_API_KEY` | Premium TTS voices (optional; OpenAI TTS works without it) |

## 3. Commerce — Stripe (optional; enables paid checkout/bookings)

Resolved by `stripe_client.py` with a **test/live mode toggle** (admin Stripe tab):

| Env var | Mode |
|---|---|
| `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` / `STRIPE_WEBHOOK_SECRET` | live |
| `STRIPE_TEST_SECRET_KEY` / `STRIPE_TEST_PUBLISHABLE_KEY` / `STRIPE_TEST_WEBHOOK_SECRET` | test |

The publishable key is browser-safe; the secret + webhook-signing keys are
server-only. (Replit-managed Stripe connections are also supported automatically.)

## 4. Messaging (optional; enables email / SMS)

| Env var | For |
|---|---|
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_WEBHOOK_SECRET` | Email (campaigns, review-asks, alerts) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS |

## 5. External lookups (optional; enable specific tools)

| Env var | Tool |
|---|---|
| `BRAVE_SEARCH_API_KEY` | Web search (falls back to Anthropic web search if absent) |
| `GOOGLE_PLACES_API_KEY`, `YELP_API_KEY`, `TRIPADVISOR_API_KEY` | Reviews aggregation |

## 6. The embed keys (per-client, publishable) — stored in the DB

The `pk_...` keys that go in the client's website embed snippet.

- **Stored in Postgres, table `tenant_embed_keys`** (plaintext — they're meant to be
  public), each with a **JSONB `origin_allowlist`**.
- **Not secret:** a request carrying the key from a non-allowlisted origin is 403'd.
  Security comes from the allowlist, not secrecy.
- **Create/manage** via the admin API: `POST /admin/api/embed-keys`
  (`{label, origin_allowlist:["https://client-site.com"]}`), `PUT`/`DELETE` on
  `/admin/api/embed-keys/<id>`. The key is returned once on create.
- Used in the snippet: `<script src=".../embed/loader.js" data-embed-key="pk_..."
  data-api-base="https://this-install"></script>`.

## 7. DB-stored secrets (encrypted at rest)

Secrets the app must recover the plaintext of (e.g. an **MCP server's
`auth_credential`** bearer token) are stored **encrypted** in Postgres via Fernet
(`encrypt_secret`/`decrypt_secret`). **The Fernet key is derived from
`FLASK_SECRET_KEY`** — so rotating `FLASK_SECRET_KEY` invalidates these. The admin
UI shows them write-masked, never plaintext.

## 8. Infra / ops (optional)

| Env var | What |
|---|---|
| `CLIENT_MODE` | `1` = this is a **client** install → the website-builder admin defaults OFF |
| `SUPER_ADMIN_KEY` | Step-up auth gating the dangerous admin surfaces (secrets, devconsole) |
| `PUBLIC_BASE_URL` / `SITE_URL` | External origin for building return URLs / callbacks |
| `FORCE_SECURE_COOKIES` | Force `Secure` session cookies (set behind HTTPS) |
| `SENTRY_DSN` / `SENTRY_ENV` | Error tracking |
| `DB_POOL_MIN` / `DB_POOL_MAX` | DB pool sizing |
| `VELO_AGENT_KEY` / `VELO_MASTER_URL` / `AGENT_API_KEY` | Agency master control channel |

---

## The two decisions you must make per client

1. **Whose provider keys?** Each silo install holds its own `OPENAI_API_KEY` /
   `STRIPE_*` / etc. Decide: the **agency** puts its own keys in every client
   install (agency pays + controls cost caps), **or** each **client** pastes their
   own into their Secrets tab. Both are supported; it's a billing decision.
2. **Set `FLASK_SECRET_KEY` explicitly and keep it stable.** It signs cookies *and*
   derives the at-rest encryption key. If it drifts (random fallback on restart),
   admins get logged out *and* any encrypted DB secrets (MCP tokens) can't be
   decrypted. Generate one per install and store it with the other infra secrets.

## Per-install provisioning checklist

```
[ ] DATABASE_URL          → the client's own Postgres (vector ext for RAG)
[ ] FLASK_SECRET_KEY      → a fresh strong value, stored stably
[ ] ADMIN_PASSWORD        → NOT "admin"
[ ] OPENAI_API_KEY and/or ANTHROPIC_API_KEY
[ ] CLIENT_MODE=1         → if this is a client (hides the website builder)
[ ] (optional) STRIPE_* / RESEND_* / TWILIO_* / lookup keys per features sold
[ ] PUBLIC_BASE_URL       → this install's external URL
[ ] FORCE_SECURE_COOKIES=1 behind HTTPS
[ ] Create an embed key (POST /admin/api/embed-keys) with the client's site origin
[ ] Drop the <script> snippet (loader.js + the embed key) on the client's site
```

**One line to remember:** a client embedding the widget only ever holds the
publishable, origin-restricted embed key — your provider/secret keys stay in the
server's environment and never leave it.
