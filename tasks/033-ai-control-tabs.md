# Task 033 — AI Control + AI Activity admin tabs (Phase 5)

**Status:** done
**Branch:** task/033-ai-control-tabs
**Depends on:** 030, 031

## Goal
Two super-admin-only dashboard tabs: AI Control (tune the knobs from 030 live) +
AI Activity (the log from 031). Plan: `PLAN_AI_CONTROL.md`.

## Acceptance criteria
- [x] Sidebar buttons (super-admin-only) + content panels for AI Control + AI Activity.
- [x] loadAiControl renders grouped knobs (toggle/number/text) with Save (PUT) +
      Reset (POST) + source badge; uses the global CSRF fetch wrapper.
- [x] loadAiActivity renders recent turns (model/rounds/tools/tokens/cost/ms/
      status) + totals + expandable redacted question/answer.

## Verification
Jinja parses; super_admin /admin renders both tabs, client renders neither (real
render path, embedded PG). All four JS functions + both panels present.

## Notes
Completes Phase 5 (030–033): the Admin AI is now panel-controlled (live, no
restart) + its activity is persisted and viewable, all super-admin-gated.
