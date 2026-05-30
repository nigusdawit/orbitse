# Task 018 — M18: multi-tenant single-DB isolation + per-tenant admin users

## Goal
Make a single shared database safely multi-tenant (resolves the security-review
finding that admin queries are global), enabling true central SaaS.

## DECISION (2026-05-29): DEFERRED — silo model chosen
The operator chose the **silo** deployment model (one app instance + one
database per client, `DEPLOY_MODE=self_host`, everything pinned to
`tenant_id=1`). Under silo, cross-tenant isolation is provided by the OS/DB
boundary — separate databases physically cannot leak into each other — so the
single-DB row-level isolation + RLS work in this task is **not needed**.

This task stays on the backlog as **deferred**: it only becomes relevant if the
product later adds a **pooled multi-tenant (central SaaS) tier** sharing one DB
across many self-serve tenants. If/when that happens, implement it as
**Postgres Row-Level Security** (tenant_id columns + RLS policies + a per-request
`app.current_tenant` session GUC set from `current_tenant_id()`), NOT by
hand-scoping every query — RLS is the category standard and is default-deny.

Central-control of the silo fleet is handled by the new **M22 fleet-sync** task
(managed defaults + local-override flag + per-tenant feature-flag rollout +
version/migration status), not by this task.

## Acceptance criteria
- [ ] Add `tenant_id` (default 1, FK tenants) to all content/runtime tables that
      lack it: gallery_cards, custom_forms/fields/submissions, chat_conversations/
      messages, generated_pages, presentations, products/orders, services/bookings,
      events, blog/team/faq/etc., agent_skills/custom_*, mcp_servers, automations,
      scrape_*, messaging_*, reviews_*, rag_*, voice_*. (Additive, idempotent.)
- [ ] Scope EVERY query by `current_tenant_id()` (reads + writes + the chat site
      index + lookups + admin views). Central-mode resolution: embed key→tenant
      (done), admin session→tenant, VELO→tenant.
- [ ] Per-tenant admin users: `admin_users` (tenant_id, email, password_hash,
      role) + login that sets `session.tenant_id`; `ADMIN_MODE` governs exposure.
- [ ] Backfill: existing rows → tenant_id=1.

## Test requirements
- Gate: two tenants' data is isolated (tenant A cannot read/delete tenant B's
  gallery/pages/chats); embed-key + admin-session tenant resolution; admin user
  login scopes session tenant.
- **security-review** (cross-tenant access) required.

## Dependencies: 010   ## Status: deferred (not needed under silo)   ## Branch: task/018-multitenant-isolation
