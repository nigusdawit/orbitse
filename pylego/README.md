# pylego

Small, generic, configurable building blocks **ported from the TypeScript Lego
library** (`~/lego/packages`) into Python for this Flask monolith. They harden
the Admin AI (`/admin/api/chat/*`) across four tracks — observability, reliability,
smarter context, safety — **strictly additively**.

## The one rule

Every module is **OFF-safe and fail-open**. With pylego disabled (or its optional
dependency / config absent) the Admin AI behaves exactly as it did before. A
pylego error can never alter or break a chat turn; only the host's *own* errors
propagate. See `PLAN_ADMIN_AI.md`.

## Modules

| Module | Ported from | Status |
|---|---|---|
| `config.py` | `@altay/typed-config` | ✅ task 026 — one env-driven settings object; per-feature `enabled`. |
| `obs.py` | `@altay/langfuse-client` | ✅ task 026 — `observe_admin_turn(meta, events)` pass-through tracer; structured local logs by default, auto-Langfuse when keys present. |
| `evals/` | `@altay/eval-harness` (+ ragas) | ✅ task 026 — dependency-free eval runner + seed admin-AI suite. |
| `llm_router.py` | `@altay/llm-router` | ✅ task 027 — `reliable_round` retry/fallback before first token + opt-in OpenAI timeout. Identity at default config. |
| `ratelimit.py` | `@altay/rate-limit` | ✅ task 027 — fixed-window limiter, Postgres (cluster-wide) or memory store, fail-open. Default off. |
| `history.py` | `@altay/chat-history` | ✅ task 028 — token-aware trim (tiktoken or chars/4 fallback); budget 0 = off; never orphans a tool msg. |
| `respcache.py` | `@altay/semantic-response-cache` | ✅ task 028 — semantic cache; admin wiring stores ONLY no-tool answers (never stale data); PII-guarded; default off. |
| `sqlguard.py` | `@altay/sql-guardrail` | ⏳ task 029. |
| `redact.py` | `@altay/pii-redact` | ⏳ task 029. |
| `structured.py` | `@altay/structured-llm` | ⏳ task 029. |
| `action_queue.py` | `@altay/admin-action-queue` | ⏳ task 029. |

## Config

All knobs read once from the environment via `pylego.config.get_config()`. Defaults
are the least-disruptive setting (observability = local logging only; everything
behavior-affecting defaults off until deliberately enabled). See `config.py`.
