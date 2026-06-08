---
name: Admin tab action authz must match tab visibility
description: Role gate + feature-route prefix for an admin tab's action endpoints must align with who can see the tab.
---

When an admin tab is client-visible (shown via `feature_visible('<flag>')` in
`templates/admin/dashboard.html`), the **action endpoints** inside that tab must be
usable by the same audience — i.e. `@admin_required` only, not `_require_super_admin_role()`.

**Why:** The Conversations inbox (Chat History tab) is client-visible, but its
takeover/release/message endpoints were gated with `_require_super_admin_role()`
(a copy-pasted guard whose 403 message literally said "Only the super admin can
manage feature visibility"). Result: client admins saw the composer but got 403
→ "Could not send reply". Keep super-admin gating only on genuinely sensitive
sub-actions (e.g. the visitor PII `/context` endpoint, which has a 403 test).

**How to apply:** (1) Match the endpoint's role gate to the tab's visibility gate.
(2) Add a `_FEATURE_ROUTE_PREFIXES` entry in `core.py` so the action endpoints are
feature-gated consistently with the tab (super-admin bypasses it anyway). A
client-visible tab whose API isn't in that list bypasses the feature flag at the
route layer. Tell-tale sign of a misapplied guard: the 403 message text doesn't
match what the endpoint actually does.
