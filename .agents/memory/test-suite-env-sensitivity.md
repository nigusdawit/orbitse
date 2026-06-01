---
name: pytest suite env sensitivity (false failures in live workspace)
description: Why tests/ shows many failures when run in the live dev workspace, and how to run them so results are meaningful.
---

Running `python -m pytest tests/` directly in the live Replit dev workspace produces a large batch of FALSE failures. They are environment/secret sensitivity, not code defects.

**Why:**
- The app boots once per session (`tests/conftest.py`) and reads real secrets that leak from the Repl's environment into pytest. conftest itself documents this for `VELO_AGENT_KEY`.
- Admin/super-admin/feature-toggle routes sit behind two layers: the `super_admin` session role AND a `SUPER_ADMIN_KEY` "unlock-key" step-up. When `SUPER_ADMIN_KEY` is present in the env (as it is in the live workspace), gated routes return 401 `super_admin_required` ("Enter the super-admin key to unlock") and the role tests fail.
- Several role/SSO tests REQUIRE harness env vars that aren't set in the bare workspace: `SSO_SIGNING_SECRET`, `CLIENT_PASSWORD` (and `ADMIN_PASSWORD`). Missing them throws `KeyError` or 401/403 mismatches.
- `test_live_call` returns `<Reject/>` (feature disabled / Twilio on placeholder creds) instead of `<Say>`/`<Stream>`.
- The secrets-manager surface (`test_admin_secrets`) needs the harness's writable env-file + unlock setup.

**How to apply:**
- To get meaningful results for the role/feature tests, run with a CLEAN env: unset the leaking deployment key and set the harness vars, e.g. `env -u SUPER_ADMIN_KEY SSO_SIGNING_SECRET=... CLIENT_PASSWORD=... python -m pytest tests/test_role_tab_control.py`. Doing this flipped the core feature-toggle tests from fail to pass, confirming the failures are config-driven.
- `pytest` is declared in `requirements.txt` but is NOT always installed in the workspace — install it before running.
- The full suite is slow (>115s) and can exceed a single command timeout before printing totals; run targeted files/subsets to get counts.
- Bottom line for assessing a merge: treat a green app boot + clean Alembic migration run + dashboard render as the primary health signal; treat raw `pytest tests/` red here as suspect until you isolate whether it's env config vs a real defect.
