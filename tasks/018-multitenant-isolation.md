# Task 018 — M18: multi-tenant single-DB isolation + per-tenant admin users

## Goal
Make a single shared database safely multi-tenant (resolves the security-review
finding that admin queries are global), enabling true central SaaS.

## OPEN DECISION (confirm first)
Implement single-DB row isolation (this task), OR keep one-DB-per-tenant and
build provisioning instead. Plan assumes single-DB isolation.

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

## Dependencies: 010   ## Status: not_started   ## Branch: task/018-multitenant-isolation
