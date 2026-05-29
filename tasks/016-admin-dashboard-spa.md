# Task 016 — M16: admin dashboard SPA — all tabs

## Goal
Grow the admin dashboard from the M2 tab set to full coverage of every
subsystem's APIs, so operators manage everything from the UI.

## Acceptance criteria
- [ ] Tabs wired to existing APIs: Cost, Skills + Custom Skills, MCP, Knowledge
      Base (RAG), Voice, Automations, Scraper, Reviews, Messaging
      (subscribers/templates/campaigns), Presentations, Products, Services,
      Bookings, Orders, Events, Analytics, Plans & Features, Embed Keys, Secrets,
      Developer Console.
- [ ] Each tab: list + create/edit/delete + the subsystem's key actions
      (e.g. automations test-run, scraper run-now, MCP test/refresh, KB upload,
      cost cap edit, embed-key allowlist editor).
- [ ] Consistent fetch wrapper (session cookie), error toasts, loading states.
- [ ] Keep it dependency-free vanilla JS (no build step) consistent with M2.

## Test requirements
- `verify` skill (M21 browser pass) drives each tab; for now: dashboard.html
  served + each tab's endpoints already gate-covered. Smoke that the page loads
  and tab switching has no console errors (Preview).

## Dependencies: 011,012,013,014,015   ## Status: not_started   ## Branch: task/016-admin-dashboard-spa
