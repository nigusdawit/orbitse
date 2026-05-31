# PLAN — Admin AI hardening, via a Python "pylego" port of the Lego patterns

**Status:** DRAFT — drafted 2026-05-31 · awaiting approval
**Initiative branches (planned):** `task/026`…`task/029` (sequential)

## Context

The in-dashboard **Admin AI** (`app.py` `/admin/api/chat/*`, `_admin_chat_stream_loop`)
is going live soon for potentially busy clients. It's already capable (SSE
streaming, 37 tools + persona routing, DB-backed editable prompt via `get_prompt`,
auto-RAG injection, cost caps, human-approved writes), but it has production gaps:
no LLM-call timeout on OpenAI, no provider fallback or retry, no per-request rate
limit, fixed 60-turn history with no token budget, no semantic response cache, no
tracing, and no evals/agent-loop tests. The user wants all four improvement tracks
— **observability+evals, reliability, smarter context, safety** — built by
**porting the relevant Lego packages' designs into Python** (the Lego library is
TypeScript; no sidecars). The outcome: a small, reusable, well-tested
`pylego/` module set wired into the admin agent, hardened for live traffic.

## Goal

A measurably better, production-ready Admin AI: every turn is traced and
cost-bounded; transient LLM failures retry and fall back across providers; busy
clients are rate-limited and never overflow the context window; repeat questions
hit a semantic cache; SQL/PII/tool-arg safety is enforced by dedicated guards; and
an eval suite + agent-loop tests gate regressions. All new logic lives in a
generic, configurable `pylego/` package (lego philosophy in Python), each module
`enabled`-flag gated so ops can disable any piece without a redeploy.

## Non-goals

- No TS sidecars (LiteLLM proxy, ragas sidecar) — user chose Python ports.
- No rewrite of the existing loop's structure — we wrap/extend `_admin_chat_stream_loop`.
- Not touching the public visitor concierge except to share primitives already shared.
- No new admin tools / no change to the approval UX (only hardening underneath).
- No change to the two-role auth or feature-flag work (024/025).

## Stack decisions

- **`pylego/` package** at repo root: one module per ported Lego pattern. Rules
  (from the Lego skill): single responsibility, `enabled: bool` no-ops gracefully,
  typed config with defaults, zero implicit globals, README per module, heavy
  comments, ≥1 test each.
- **Reuse, don't duplicate**: `get_prompt` (app.py:18082), `record_chat_cost` +
  `enforce_cost_cap` (cost.py / app.py:4498+), `rag.py`, `semantic_cache.py`
  (visitor cache — generalize for admin), existing token-bucket limiter pattern
  (app.py:515), `admin_pending_actions` + `admin_setting_snapshots`.
- **Optional deps, lazy-imported**: `langfuse` (Python SDK), `ragas`, `tiktoken`,
  `sqlparse` — each guarded so the app boots/serves if the dep or its env config
  is absent (honest graceful degradation, not silent breakage).
- Integration tests via the established **embedded-Postgres** harness (`pgserver`
  under `uv run`).

## The pylego modules (port → wire)

| Module | Lego source (pattern) | What it does in Python | Wires into |
|---|---|---|---|
| `pylego/config.py` | typed-config | One typed settings object for every knob + `enabled` flag; env-driven, sane defaults | all modules |
| `pylego/obs.py` | langfuse-client | Thin tracing wrapper over the **langfuse Python SDK**; no-op if unconfigured; spans per turn/round/tool/retrieval + usage tags | `_admin_chat_stream_loop` |
| `pylego/evals/` | eval-harness + ragas-runner | Python eval runner (cases + `regex`/`json_schema`/`llm_judge` assertions + JUnit-ish report); optional **ragas** scoring for the RAG path; seed admin-AI suite | CI + manual |
| `pylego/llm_router.py` | llm-router (logic, not the proxy) | Provider fallback chain (OpenAI⇄Claude), bounded retry w/ exp backoff, explicit per-call timeout, budget hook reusing cost caps | `_stream_round_openai` (13392) / `_stream_round_claude` (11187) call sites |
| `pylego/ratelimit.py` | rate-limit | Fixed-window limiter, pluggable store (in-memory default; **DB store for multi-worker gunicorn**); per-session + per-tenant | admin chat endpoints (19292/19311) |
| `pylego/history.py` | chat-history | **Token-aware** trim (tiktoken budget) on top of the existing orphan-prune; never overflow context | history build (app.py:18930) |
| `pylego/respcache.py` | semantic-response-cache | Admin-surface semantic cache: embed question, PII-guard the response, content-version eviction, `enabled` no-op | top of the loop, before round 1 |
| `pylego/sqlguard.py` | sql-guardrail | `sqlparse`-based read-only validator (single stmt, SELECT/WITH only, no DDL/DML/multi-stmt) | `admin_run_sql` tool |
| `pylego/redact.py` | pii-redact | Secret/PII redactor applied to history + tool output before LLM, cache, and traces | loop + obs + respcache |
| `pylego/structured.py` | structured-llm | pydantic-validated tool-arg parse + retry-with-error-feedback | `execute_admin_tool` arg parsing |
| `pylego/action_queue.py` | admin-action-queue | Idempotency keys + explicit status transitions over `admin_pending_actions` | approve/reject routes |

## Execution phases → tasks (sequential; all touch `_admin_chat_stream_loop`, so not parallel)

- **Task 026 — Foundation + Observability + Evals.** `pylego/` scaffolding +
  `config.py` + `obs.py` (langfuse) + `evals/` (harness + optional ragas) + seed
  eval suite + **first integration tests of the admin loop** (embedded PG). Wire
  tracing into the loop. *Highest leverage — makes every later change measurable.*
- **Task 027 — Reliability.** `llm_router.py` (fallback + retry + timeout) +
  `ratelimit.py` (DB-backed for multi-worker). Wire into the round calls +
  endpoints. Graceful degradation when a provider is down.
- **Task 028 — Smarter context.** `history.py` token-trim + `respcache.py`
  semantic cache (+ optional cross-chat memory if `rag_chat_turns` is dormant).
  Cuts cost + latency for busy clients; prevents context overflow.
- **Task 029 — Safety hardening.** `sqlguard.py` + `redact.py` + `structured.py`
  + `action_queue.py` hardening. Run `security-review` on this one.

## Env / config surface (names only)

`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`,
`ADMIN_CHAT_RATE_LIMIT` / `_WINDOW`, `ADMIN_CHAT_HISTORY_TOKEN_BUDGET`,
`ADMIN_CHAT_LLM_TIMEOUT` / `_MAX_RETRIES`, `ADMIN_CHAT_PROVIDER_FALLBACK`,
`ADMIN_RESPCACHE_ENABLED` / `_THRESHOLD`, plus an `enabled` flag per module.
All optional with safe defaults; absent config = feature off / current behavior.

## Testing strategy

- **Unit** (fast, no DB) per pylego module: ratelimit windows, sqlguard
  accept/reject corpus, redact patterns, history token-trim boundaries, llm_router
  fallback/retry (mocked transport), respcache key/PII/version logic.
- **Integration** (embedded Postgres): admin loop end-to-end — a turn traces,
  rate-limits, trims, caches, and falls back; the approval flow stays intact.
- **Evals**: seed suite of admin-AI cases (tool selection, SQL safety refusals,
  RAG faithfulness via ragas) runnable in CI; baseline captured in 026.
- **Gate** per task: byte-compile + pyflakes clean; new tests green; existing
  `tests/` + `test_role_tab_control.py` not regressed; `security-review` on 029;
  `verify` (load `/admin`, run an admin-chat turn) after 026 and 028.

## Verification (definition of done, whole initiative)

Boot against embedded Postgres; run an admin chat turn and confirm: a Langfuse
trace is emitted (when configured), a forced OpenAI timeout falls back to the
configured fallback provider, a flood of requests gets 429s, an over-long history
is trimmed to the token budget without a provider 400, a repeat question is served
from cache, `admin_run_sql` rejects a non-SELECT, and the eval suite passes its
baseline. Merge each task to `main` and push.

## Resolved decisions

1. **Observability backend:** `obs.py` emits **structured local logs by default** and
   auto-upgrades to **Langfuse** (Python SDK) when `LANGFUSE_*` keys are present —
   zero external dependency to start, full tracing when keys are set. (026)
2. **Rate-limit + cache store:** **DB-backed (Postgres)** so limits/caches are
   enforced cluster-wide regardless of gunicorn worker count — safest for a busy
   client and multi-worker autoscale. In-memory remains the pluggable default for
   tests/dev. (027/028)

No open questions remain.
