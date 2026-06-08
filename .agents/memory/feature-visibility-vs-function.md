---
name: Feature gating — function vs visibility are two knobs
description: tenant_features has TWO independent gates; admin UI uses feature_visible(), backend uses tenant_has_feature().
---

# Per-feature gating has two independent knobs

A feature in `tenant_features` is governed by **two** separate columns/helpers,
not one:

- **`enabled`** → the **backend function** gate. Enforced by
  `enforce_feature_flags()` (a global `before_request` in app.py keyed off
  `_FEATURE_ROUTE_PREFIXES`); a disabled feature's API returns 403 (or 404 for
  public GETs). Read via `tenant_has_feature(name)`.
- **`visible`** → the **admin UI visibility** gate only. Read via
  `tenant_feature_visible(name)`. The `visible` column is **nullable** and
  **NULL means "inherit from enabled"** — so a site that never sets visibility
  behaves exactly as the old single-flag world (shown iff enabled).

**Why:** an operator needed to hide a feature from a client's menu without
turning the function off (and the reverse — show a feature as a teaser while its
API stays disabled), without changing the long-standing single-flag behavior for
everyone else. Keeping `visible` NULL-by-default makes the change additive.

**How to apply:**
- New admin **sidebar/tab visibility** gates in `templates/admin/dashboard.html`
  (and tab partials) must use `feature_visible('x')`, NOT `has_feature('x')`.
  Both are passed into the dashboard render context; `feature_visible` is the
  visibility one. (`has_feature` is still passed for back-compat.)
- New **route/function** gates stay on `tenant_has_feature` /
  `_FEATURE_ROUTE_PREFIXES` — never gate the backend on visibility.
- Setting visibility uses `set_tenant_feature_visible()` (writes only `visible`,
  seeds `enabled` from the registry default on insert). `set_tenant_feature()`
  still writes only `enabled`.
- There are TWO caches now: `_FEATURE_CACHE` (enabled) and `_FEATURE_VIS_CACHE`
  (visible); `invalidate_tenant_features_cache()` clears both — keep it that way.
- Super-admin bypasses backend gates and always sees the UI (unchanged).
- The PATCH `/admin/api/tenant/features/<name>` accepts `enabled` and/or
  `visible` independently (super-admin only).
