# Verification report & runbook (M21)

This is the M21 deliverable: what is **automatically verified**, what needs a
**real environment** (browser / live keys / Docker / WordPress), and the exact
commands to run each.

---

## Automated — green (run in CI on every push, see `.github/workflows/ci.yml`)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check admin_ai_platform _gate_runner.py` | **PASS** (clean) |
| Integration gate (embedded Postgres + pgvector) | `uv run --python 3.12 --with pgserver --with pytest --with python-pptx --with cryptography --with rjsmin python _gate_runner.py` | **PASS — 377/377** |
| Unit suite | `uv run --python 3.12 --with psycopg2-binary --with pytest --with flask --with openai --with cryptography --with python-pptx --with rjsmin python -m pytest admin_ai_platform/tests -q` | **PASS** (71 passed, 2 skipped) |
| Dashboard inline-JS syntax | `node` `new Function()` over the `<script>` block | **PASS** |
| Loader/widget JS syntax | `node --check embed/loader.js …` | **PASS** |
| WordPress plugin lint | `php -l wordpress-plugin/*.php` | runs in CI (no PHP in the dev sandbox) |

The gate exercises every subsystem against a real Postgres: visitor chat tools,
admin auth + CSRF, cost, skills/MCP (+ secrets-at-rest), RAG, automations,
scraper ticks, messaging, reviews aggregation, presentations import, commerce
(Stripe webhook idempotency + refund hardening), events ticketing, analytics,
onboarding `/setup`, the admin dashboard serve, deploy bundle + snapshot CLI, and
fleet-sync versioned merge. Two milestones with a trust boundary (M11 Stripe,
M19 security, M22 fleet) each passed an independent security review.

---

## Needs a real environment (NOT runnable in the dev sandbox — no browser / keys / Docker / PHP)

A throwaway launcher is provided: **`_preview_app.py`** boots an embedded Postgres
+ the app on `http://127.0.0.1:5055` (admin password `admin`). Use it for the
browser passes.

### 1. Browser E2E
```bash
uv run --python 3.12 --with pgserver --with python-pptx python _preview_app.py
# then drive with Playwright or the Preview MCP:
```
- [ ] `/demo` — gallery navigate, live `generatePage` render, conversational form
      submit, spoken reply (needs an OpenAI key for the last two).
- [ ] `/admin` (login `admin`) — each tab renders, no console errors; create/edit/
      delete on a couple of resources; CSRF header is sent on writes.
- [ ] A cross-origin test page loads `/embed/loader.js` with a tenant embed key →
      widget mounts in a Shadow DOM; chat works under CORS; a request from a
      non-allowlisted origin gets 403.

### 2. Live-key E2E smoke (opt-in via env)
Set the relevant keys, then:
- [ ] `POST /api/chat` returns a streamed answer (OpenAI/Anthropic).
- [ ] Voice: `/api/voice/tts` returns audio; `/api/voice/stt` transcribes (needs
      `OPENAI_API_KEY`; ElevenLabs optional).
- [ ] RAG: upload a doc via `/admin/api/kb/upload`, then `lookup_knowledge_base`
      retrieves a chunk (needs pgvector + OpenAI embeddings).
- [ ] Stripe **test mode**: product checkout → Stripe Checkout → webhook
      `checkout.session.completed` → order flips `paid`, stock decrements.
- [ ] Resend email + Twilio SMS send (campaign / review-ask).

### 3. WordPress
- [ ] `php -l wordpress-plugin/ai-concierge.php` (CI does this).
- [ ] Install the plugin zip into a local WP (wp-env/Docker), set embed key + API
      base → widget auto-injects; the wp-admin "AI Concierge" page loads the
      hosted admin via a single-use SSO token; a forged/expired token is rejected.

### 4. Docker / deploy
- [ ] `docker compose up --build` → `/healthz` 200; schema bootstraps; `/setup`
      provisions; widget bundle served from `/embed/dist/...` with immutable cache.
- [ ] Railway (`railway.json`) and Render (`render.yaml`) blueprint deploys.

---

## Known residuals (carry-forward, none blocking)

- **Browser/live-key/WP/Docker passes** above are unverified *in this sandbox* by
  necessity (no browser, no keys, no Docker, no PHP). They are scripted/checklisted
  here and run in CI where the runner provides PHP + Node.
- **M18 (single-DB RLS isolation)** — intentionally deferred; not needed under the
  chosen **silo** model (one DB per client). Revisit only for a pooled central-SaaS
  tier.
- **Fleet-sync consumers** — the versioned-merge engine + control channel are done
  and tested; wiring each specific managed default (e.g. the live system prompt) to
  read `fleet.effective_value()` is a thin per-consumer follow-on.
