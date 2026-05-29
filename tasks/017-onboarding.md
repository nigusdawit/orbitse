# Task 017 — M17: onboarding (operator /setup wizard + client checklist + AI assistant + agency provisioning)

## Goal
Make first-run + client + agency onboarding self-serve.

## Acceptance criteria
- [ ] Operator first-run `/setup` wizard (auto-closes after completion): pick a
      preset (generic/restaurant/…), enter business name, paste keys, set admin
      password, → provisions settings + seed content + the first embed key, then
      returns 404 to others. (Port the spirit of the original /setup + onboarding_templates.)
- [ ] Client onboarding checklist in admin: a guided panel ("add your content →
      get an embed key → paste the snippet → try it") with live completion state.
- [ ] AI onboarding assistant: the admin AI with an onboarding system prompt +
      a few onboarding tools (create embed key, seed sample gallery, run a test
      chat) so a client can be walked through setup conversationally.
- [ ] Agency provisioning UI: create a tenant, clone a snapshot into it, issue
      embed + SSO keys — wrapping the existing snapshot/apply + VELO bootstrap.

## Test requirements
- Gate: /setup provisions then self-closes (second GET 404); checklist status
  endpoint reflects real state; agency-provision creates tenant + applies snapshot.

## Dependencies: 016   ## Status: not_started   ## Branch: task/017-onboarding
