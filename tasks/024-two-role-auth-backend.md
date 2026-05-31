# Task 024 — Two-role admin (super-admin/client): backend

**Status:** in_progress
**Branch:** task/024-two-role-auth-backend
**Depends on:** —
**Parallel-with:** — (025 depends on this)

## Goal

Add a login-level role (super_admin vs client) on top of the existing single
admin login, make the super admin bypass feature-flag gating, complete the
feature registry so every tab has an on/off flag, and hard-reject clients from
the feature-toggle endpoints. Full design: `~/.claude/plans/serialized-floating-boot.md`.

## Research block (verified in plan mode)

- `admin_login()` app.py:5583; `admin_sso()` 5568; `admin_logout()` 5618;
  `admin_required` 5269; `ADMIN_PASSWORD` 536.
- Feature system: `_FEATURE_REGISTRY` 3982, `tenant_has_feature` 4067 (fails OPEN
  on unknown names), `set_tenant_feature` 4177, `list_tenant_features` 4109,
  `_FEATURE_ROUTE_PREFIXES` 4199, `_enforce_feature_flags` 4242.
- Existing unlock-key step-up `_SUPER_ADMIN_PROTECTED_PREFIXES` 5649 (incl.
  `/admin/api/tenant/features`) — keep as-is.
- tenant/features handlers ≈ app.py:38705-38758.

## Acceptance criteria

- [ ] `CLIENT_PASSWORD` env read; added to env_manager whitelist.
- [ ] `admin_login` sets `session["admin_role"]` on each branch; `/admin/sso` →
      client; logout pops role.
- [ ] `_is_super_admin()` requires logged-in (False for anon/client); Jinja
      global `is_super_admin` registered.
- [ ] `_enforce_feature_flags` early-returns for super_admin only.
- [ ] Registry has one flag per ungated tab (defaults per plan); route prefixes
      added for the new flags.
- [ ] `/admin/api/tenant/features` GET+PATCH return 403 for a client session.
- [ ] Startup assertion: every `_FEATURE_ROUTE_PREFIXES` feature ∈ `_FEATURE_NAMES`.

## Test requirements

`tests/test_role_tab_control.py` (embedded Postgres): tests 1-6 from the plan
(super_admin login+toggle; client login → 403 on features GET/PATCH; super_admin
flag-bypass vs client gated; anon still gated [R2]; SSO→client; startup assertion
holds).

## Commits

(filled as work progresses)

## Drift reason

(blank)

## Notes

Validated by an independent design review; two HIGH fixes baked into the plan:
(1) role check must be in the tenant/features handler, not just the template;
(2) `_is_super_admin()` must require logged-in so the flag bypass never leaks to
anonymous/public traffic.
