# IFTTT Automation Engine

## When to use
You want admins to wire up "When X happens, do Y" rules from a UI without writing code — e.g. *when a form is submitted with score > 80, send the lead an email and add them to a SMS broadcast*; *when a Stripe payment succeeds, post to Slack*; *every day at 9am, send the digest*. Same shape as Zapier / IFTTT, but in-process and tenant-scoped.

## Architecture
Three moving parts:

1. **Trigger registry** (`TRIGGER_TYPES`) and **action registry** (`ACTION_TYPES`) — plain Python dicts keyed by string name, each entry declares its display label, parameter schema (for the admin UI), and a handler function.
2. **Dispatch path** for event-driven triggers — call sites in the rest of the codebase call `automations.dispatch_event("form_submitted", payload)`; the engine looks up matching automations for the active tenant, evaluates per-rule conditions against the payload, and executes the action chain.
3. **Scheduler tick** for time-based triggers (`daily_at`, `weekly_on`, `interval`) — registered with the in-process tick scheduler (see `01-in-process-tick-scheduler.md`).

Two safety rails:
- **Merge tags** in action params (`{{form.email}}`, `{{trigger.amount}}`) are substituted via a single `_MERGE_RE` regex against the payload — never `eval`, never templating-engine sandbox-escape.
- **Concurrency cap** (`MAX_CONCURRENT_RUNS = 5`) on a module-level semaphore so a runaway loop or a 5,000-row backfill can't fan out into thousands of simultaneous outbound calls.

Note: there is no two-step confirm-token flow inside the IFTTT engine itself — destructive guarantees come from the action implementations (e.g. "send_email" doesn't double-send because messaging dedupes by content+recipient hash) and from the once-per-period idempotency pattern at the trigger site. If you need an in-engine confirmation flow, lift the pattern from the VELO bridge (`velo_endpoints._make_confirm_token` / `_consume_confirm_token`) and gate destructive `ACTION_TYPES` entries on it.

## Data model
- `automations` — id, tenant_id, name, trigger_type, trigger_params JSONB, enabled, created_at.
- `automation_actions` — id, automation_id, sort_order, action_type, action_params JSONB.
- `automation_runs` — id, automation_id, status (`pending`/`running`/`success`/`error`/`skipped`), started_at, finished_at, trigger_payload JSONB, error_text. Retention: a tick periodically deletes rows older than ~30 days.

## API surface
- `automations.dispatch_event(event_name, payload)` — call from any business-logic site.
- `automations.register_trigger(name, label, schema, handler)` / `register_action(...)` — extension points.
- HTTP: `/admin/api/automations` CRUD, `/admin/api/automations/<id>/run` (manual fire), `/admin/api/automations/<id>/runs` (history).
- For confirm-token flows, see the VELO bridge's pattern (not implemented in this engine).
- Webhook receivers (`/api/webhooks/<source>`) verify signature (`hmac_sha256`, Stripe's `t=…,v1=…`, GitHub's `X-Hub-Signature-256`) before calling `dispatch_event`.

## Key files
- `automations.py` — engine, registries, scheduler tick.
- `velo_endpoints.py` — reference implementation of a confirm-token flow you can borrow from.
- `app.py` — webhook routes that funnel into `dispatch_event`.

## External deps
Whatever the registered actions need — Resend (email), Twilio (SMS), Stripe SDK, requests for outbound HTTP. The engine itself has no external deps.

## Pitfalls
- **Trigger storms.** A bulk import that fires `customer_created` for 10k rows will queue 10k runs — the concurrency cap throttles execution, not queueing. Add a "skip when bulk_import=true" guard at the call site.
- **Merge-tag injection.** Treat substituted output as untrusted in any downstream context (HTML email body → escape; SQL → never interpolate). The engine substitutes raw strings.
- **Webhook signatures** must be verified BEFORE parsing the body for `dispatch_event` — otherwise an attacker can craft a body that triggers an action and you've just verified your own forged payload.
- **Tenant scoping.** `dispatch_event` must run inside a request (or set tenant context explicitly); a tick-fired event needs to loop tenants itself.
- **Action ordering** is sequential within one run — a slow action delays the next. For fanout, register an action that itself enqueues to a queue.

## Adaptation notes
- Adding a new trigger: append to `TRIGGER_TYPES`, then call `dispatch_event("your_new_name", payload)` from the relevant call site.
- Adding a new action: append to `ACTION_TYPES` with a handler that takes `(params, payload, run_context)`. Mark destructive ones `requires_confirmation=True`.
- For multi-process deployments, swap the in-memory semaphore for a Postgres advisory lock or a Redis counter.

## Adoption checklist
- [ ] Lift `TRIGGER_TYPES` / `ACTION_TYPES` shape and the dispatch loop from `automations.py`.
- [ ] Decide which existing events should fire `dispatch_event` — form submit, order paid, signup, webhook received are the usual four.
- [ ] Wire the time-based triggers into your tick scheduler.
- [ ] Verify webhook signature handling for every external source you accept.
- [ ] Before exposing any destructive action (refund, delete, mass-send), add a confirm-token gate — borrow the VELO bridge's pattern.
- [ ] Build the admin UI: list, edit, enable/disable, run-now, view runs.
