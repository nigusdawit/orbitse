# Parallel Subagents (`spawn_agents` Fan-Out)

**Category:** AI / LLM Pipelines

## When to use
A single user request decomposes into 2–5 independent subtasks ("audit
SEO + draft a blog post + summarize last week's bookings"). Running
them sequentially in one chat thread is slow and token-bloated;
fanning out is faster and cheaper because each worker carries only
the tool subset and context it needs.

## Architecture
- One model-facing tool: `spawn_agents`. Schema: `tasks: [{description,
  persona?, max_rounds?}]`. The model calls it once with up to N
  tasks.
- Implementation runs every task in a `ThreadPoolExecutor` (size =
  per-tenant `max_parallel_subagents`, default 5, capped at 10).
- Each worker:
  - Spins up an isolated copy of the standard tool-call loop, NOT
    streaming (the user is waiting on the orchestrator's stream).
  - Uses the persona's system prompt + tool subset, with
    `spawn_agents` itself REMOVED from the worker's tool list — no
    recursive fan-out.
  - Returns `{result, prompt_tokens, completion_tokens, cost_usd,
    duration_ms, error?}`.
- Quota: atomic per-tenant daily counter via `INSERT ... ON CONFLICT
  DO UPDATE WHERE count+req <= cap RETURNING`. The conditional
  UPDATE is the gate — when it fails to RETURN a row, quota would be
  exceeded and the call is rejected before any worker spins up. This
  is race-safe without explicit locks.
- Every worker logs to `admin_subagent_runs` (sub_task, persona,
  model, tokens, cost, duration, status, result preview). Costs also
  flow into the standard cost ledger so they appear in the dashboard
  alongside everything else.

## Data model
- `admin_subagent_runs (id, tenant_id, parent_session_id, sub_task,
  persona, model, prompt_tokens, completion_tokens, cost_usd,
  duration_ms, status, result_preview, error_text, created_at)`.
- `admin_subagent_daily_counters (tenant_id, day, count,
  PRIMARY KEY (tenant_id, day))` — atomic counter.
- `tenant_cost_caps.max_parallel_subagents INT DEFAULT 5`,
  `tenant_cost_caps.daily_subagent_runs_cap INT DEFAULT 50`.

## API surface
- Model-facing tool only. No HTTP endpoint to invoke it directly.
- `GET /admin/api/chat/subagent-runs` for the admin to inspect runs.

## Key files
- `app.py` — `_admin_tool_spawn_agents` (~line 17081), atomic counter
  UPSERT (~16899), worker function with `spawn_agents` filtered out
  of its tool list (~16981).

## External deps
- Python `concurrent.futures.ThreadPoolExecutor` (or any equivalent
  in your stack — async/await also works).

## Pitfalls
- **Recursive fan-out** is the #1 footgun — strip `spawn_agents` from
  every worker's tool list, or one bad call can detonate the quota.
- Workers must NOT stream — the parent owns the user's HTTP stream.
- Worker errors must surface as `{error: ...}` results, never thrown
  exceptions, or one bad subtask kills the whole batch.
- Database connections in workers: use a pooled DB layer or each
  worker opens its own connection (don't share one across threads).
- Quota gate must be conditional UPSERT, not SELECT-then-INSERT —
  the latter races and double-counts.
- Worker results can be large; cap `result_preview` (e.g. 2 KB) and
  store the full result in the parent thread's context, not back into
  the run log.

## Adaptation notes
- The pattern is provider-agnostic: any non-streaming chat completion
  call can serve as the worker.
- For 1-tenant apps, drop `tenant_id` and use a single global counter
  row keyed by `day`.
- A FastAPI/async stack can use `asyncio.gather` instead of a thread
  pool; semantics are otherwise identical.

## Related skills
- `06-persona-router.md` — each worker is constrained to a persona's
  tool subset.
- `01-streaming-tool-call-loop.md` — both the parent's streaming
  loop and each worker's non-streaming loop reuse this pattern.
- `../auth/02-multi-tenant-scaffolding.md` — quotas and run logs
  live in tenant scope.
