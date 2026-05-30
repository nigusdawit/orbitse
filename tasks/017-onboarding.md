# Task 017 — M17: onboarding (operator /setup wizard + client checklist + AI assistant + agency provisioning)

## Goal
Make first-run + client + agency onboarding self-serve.

## Acceptance criteria
- [x] Operator first-run `/setup` wizard (auto-closes after completion): pick a
      preset (generic/restaurant/salon/retail), enter business name, set admin
      password → provisions business_info + chatbot greeting + seed experiences +
      the first embed key, then returns 404 to others. (Provider keys stay in env
      / the M19 secrets store, not the DB — noted on the form.)
- [x] Client onboarding checklist in admin: `GET /admin/api/onboarding/checklist`
      with live per-step completion (business named / content / embed key /
      chatbot enabled / had a chat).
- [x] AI onboarding assistant: onboarding system prompt endpoint + onboarding
      tools (seed-sample gallery, create embed key via existing tenancy route) so
      the admin AI can walk a client through setup.
- [x] Agency provisioning: `POST /admin/api/onboarding/provision-tenant` creates
      a tenant, issues its embed key, and applies a snapshot's gallery cards.

## Test requirements
- Gate: /setup provisions then self-closes (second GET 404); checklist status
  endpoint reflects real state; agency-provision creates tenant + applies snapshot.

## Dependencies: 016   ## Status: done   ## Branch: task/017-onboarding

## Notes
Merged to main (--no-ff). Gate: 322/322 incl. /setup open→provision→self-close
(404 after), short-password reject, preset seed, hashed-password override (new
pw logs in, old env pw rejected), checklist state, seed-sample, assistant-prompt,
agency provision-tenant (+ snapshot card). Unit: `test_onboarding.py` pins
pbkdf2 hashing + check_admin_password env/DB branches + preset shape. Fixes:
tenants SERIAL sequence (seeded id=1 didn't advance it → first auto-id collided);
gallery_cards seed needed image_url (NOT NULL). Provider-key paste intentionally
deferred to the M19 secrets-at-rest store (env is the secure path for now). Also
flagged a pre-existing M6 bug (services/rules TIME columns aren't JSON
serializable) as a separate task.
