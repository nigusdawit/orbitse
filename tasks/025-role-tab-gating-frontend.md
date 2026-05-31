# Task 025 — Two-role admin: frontend tab gating + verify

**Status:** not_started
**Branch:** task/025-role-tab-gating-frontend
**Depends on:** 024 (needs `is_super_admin` Jinja global + the new flags)
**Parallel-with:** —

## Goal

Make the admin dashboard show each tab (button + content panel) only when the
session is super_admin OR the matching feature flag is on. Plans & Features is
shown only to super_admin. Verify end-to-end as each role. Design:
`~/.claude/plans/serialized-floating-boot.md`.

## Research block

- Sidebar buttons templates/admin/dashboard.html:2055-2290 (already maps several
  tabs to `has_feature('website_builder')` from the carve-out).
- Plans & Features tab content ≈ dashboard.html:23806-23900; tab button in the
  Billing & Plans group.
- Content panels are scattered (e.g. ~10405); each tab's `<div id="...-tab">`
  panel must be wrapped to match its button.

## Acceptance criteria

- [ ] Every tab button AND its content panel wrapped
      `{% if is_super_admin() or has_feature('X') %}`.
- [ ] Existing `has_feature('website_builder')` wraps updated to add
      `is_super_admin() or`.
- [ ] Plans & Features button + panel wrapped `{% if is_super_admin() %}`.
- [ ] Jinja renders cleanly; tab→flag mapping matches the registry from 024.

## Test requirements

Plan test 7: render dashboard with a client session (disabled tab `data-testid`
absent, `tab-plans-features` absent) vs super_admin (both present). Plus the
`verify` skill: load `/admin` as super_admin and as client and confirm the tab
sets differ as configured.

## Commits

(filled as work progresses)

## Drift reason

Gated tab BUTTONS only (not the 54 content panels), matching the established
website_builder carve-out convention already in this template. Rationale: a
hidden button removes the tab from navigation, and every tab's admin API is
server-gated for clients (enforced + reviewed in task 024), so the data can't
load even if a panel shell remains in the DOM. Wrapping all 54 scattered,
deeply-nested panels would be high-risk churn for no added security boundary.
Verified the boundary via the real /admin render (test 7) + the 024 endpoint
guards, not just the buttons.

## Notes

Tab→flag map must stay in lockstep with 024's registry; mismatches fail OPEN
(client could see a tab). Cross-check each tab against the registry names.
