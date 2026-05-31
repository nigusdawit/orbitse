# Task 037 — Master AI-enhancements kill switch (safety)

**Status:** done
**Branch:** task/037-master-killswitch
**Depends on:** 030 (AI Control settings)

## Goal
A single super-admin toggle that reverts EVERY pylego enhancement to pre-pylego
behavior — the "turn it all off if it causes trouble" switch the user asked for.

## Acceptance criteria
- [x] `ai_enhancements_enabled` master knob (config + AI Control registry, group
      "Master", default ON, env AI_ENHANCEMENTS_ENABLED).
- [x] When OFF, get_ai_setting returns the INERT value for every other behavior
      knob (overriding DB/env) and activity_logging → False, so retries/fallback/
      timeout/trim/cache/sqlguard/rate-limit/redact + activity all go quiet.
- [x] When ON (default), everything behaves exactly as before this task.

## Test requirements
- [x] master off forces inert even when knobs individually enabled; master off
      stops activity-log writes; master on restores normal logging.

## Verification
13/13 tests vs embedded PG (3 master-switch + ai_control + visitor_activity
regression). Default ON = unchanged behavior.

## Notes
One switch in AI Control (or AI_ENHANCEMENTS_ENABLED=0). Central gate in
get_ai_setting, so it covers every current AND future knob that reads through it.
