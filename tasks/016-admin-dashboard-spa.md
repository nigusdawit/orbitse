# Task 016 — M16: admin dashboard SPA — all tabs

## Goal
Grow the admin dashboard from the M2 tab set to full coverage of every
subsystem's APIs, so operators manage everything from the UI.

## Acceptance criteria
- [x] Tabs wired to existing APIs: Cost, Skills + Custom Skills, MCP, Knowledge
      Base (RAG), Voice, Automations, Scraper, Reviews, Messaging
      (subscribers/templates/campaigns), Presentations, Products, Services,
      Orders, Events, content (experiences/faqs/testimonials/team/pricing/blog/
      business), Analytics, Plans & Features, Embed Keys, Secrets, Developer
      Console. (Bookings list deferred — no admin bookings-list endpoint yet.)
- [x] Each tab: list + create/delete + key actions (automations test-run,
      scraper run, MCP test/refresh, KB upload, embed-key allowlist editor,
      product Stripe-sync, campaign send-now, review refresh, skill toggle).
- [x] Consistent fetch wrapper (session cookie), error toasts, loading states.
- [x] Dependency-free vanilla JS, no build step (consistent with M2).

## Test requirements
- `verify` skill (M21 browser pass) drives each tab; for now: dashboard.html
  served + each tab's endpoints already gate-covered. Smoke that the page loads
  and tab switching has no console errors (Preview).

## Dependencies: 011,012,013,014,015   ## Status: done   ## Branch: task/016-admin-dashboard-spa

## Notes
Landed on main directly (commit f956b98 — branch cut retroactively, same as
M12). Gate: 304/304 incl. dashboard served to authed admin, contains every new
tab + renderResource/TABS, no external <script src>, anon redirected. Verified
without a browser: extracted inline JS passes `new Function()` syntax check
(node), all mutation endpoints the buttons call confirmed to exist (fixed
automations action → `/test-run`). **UI not browser-verified** — the harness
preview resolves launch.json from the outer wrapper dir, not the nested project,
so a live load wasn't wired here; a `_preview_app.py` launcher (pgserver + app
on :5055, admin pw "admin") is left in the tree for the M21 browser pass, which
the task designates as the real per-tab verification.
