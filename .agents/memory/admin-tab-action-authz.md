---
name: Admin tab action authz must match tab visibility
description: Role gate + feature-route prefix for an admin tab's action endpoints must align with who can see the tab.
---

When an admin tab is client-visible (shown via `feature_visible('<flag>')` in the
dashboard template), the **action endpoints** inside that tab must be usable by the
same audience — i.e. `@admin_required` only, not `_require_super_admin_role()`.

The Chat History inbox's **visitor context** side-panel endpoint
(`/admin/api/conversations/<id>/context`) is `@admin_required` (NOT super-admin) by
explicit user decision — in this single-tenant template the admin IS the operator
and needs lead score / interests / source / linked-lead to handle a chat. Do not
re-gate it to super-admin. The frontend's 403 branch is now defensive only.

**Why:** A client-visible inbox once had its reply/takeover endpoints gated to
super-admin only, so client admins saw the composer but every action 403'd with a
confusing message. Tell-tale sign of a misapplied guard: the 403 message text
describes something the endpoint doesn't actually do (a copy-pasted gate).

**How to apply:** (1) Match the endpoint's role gate to the tab's visibility gate.
(2) Add a matching `_FEATURE_ROUTE_PREFIXES` entry in `core.py` so the action
endpoints are feature-gated consistently with the tab (super-admin bypasses it
anyway). A client-visible tab whose API prefix isn't in that list bypasses the
feature flag at the route layer.
