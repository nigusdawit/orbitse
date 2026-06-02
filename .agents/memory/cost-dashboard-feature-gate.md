---
name: cost_dashboard feature gate vs tests
description: Why the 4 /admin/api/cost/* HTTP tests can 404, and that it is not a code break.
---

The `/admin/api/cost/*` routes are gated by `tenant_has_feature("cost_dashboard")`; when off they return `404 {"error":"cost dashboard not enabled"}`.

`tenant_has_feature` (in `core.py`): UNKNOWN feature names fail OPEN (return True); KNOWN names read `tenant_features.enabled`, lazy-seeding the registry default on first lookup. `cost_dashboard`'s registry default is True, but a `tenant_features` row with `enabled=False` (a deliberate/earlier toggle) overrides it.

**Why this matters:** the cost HTTP tests in `tests/test_cost_infra.py` assume the flag is ON but never enable it, so they 404 when the DB row says disabled. This is a test-fixture/data-toggle state, NOT a regression — the cost route code, infra, and unit-level tests are fine.

**How to apply:** if cost HTTP tests fail with 404 "not enabled", enable the flag first (`app.set_tenant_feature("cost_dashboard", True, tenant_id=1)`) or via the Plans & Features admin tab — do not assume the merge broke the cost dashboard.
