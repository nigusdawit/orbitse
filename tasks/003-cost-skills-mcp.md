# Task 003 — M3: Cost + Skills/MCP

## Goal
Cost dashboard blueprint (summary/series/by-surface/by-model/prices/cap) + caps (alert/throttle/block)
+ weekly digest tick; skills registry + custom SQL/HTTP/webhook skills; MCP servers + OAuth.

## Acceptance criteria (to expand on first touch)
- [ ] `blueprints/cost.py` (`/admin/api/cost/*`); digest tick registered with scheduler.
- [ ] `blueprints/skills.py` (`/admin/api/skills`, custom-sql/webhook, `/admin/api/chat/skills`).
- [ ] `blueprints/mcp.py` (`/admin/api/mcp/*` + oauth callback).

## Test requirements (to expand)
- pytest: cost stamping immutability, cap behavior (alert/throttle/block), skill name validation,
  SQL-skill parameter binding safety.

## Dependencies: 002   ## Parallel-with: 004
## Status: done (merged)   ## Branch: task/003-cost-skills-mcp

## Verification (embedded-Postgres gate, 70/70 green)
- cost: summary/series/by-surface/by-model 200; prices list + PATCH; cap PUT +
  reject bad behavior; feature-gated (404 when cost_dashboard off)
- skills: registry lists builtins; builtin delete refused; custom name validation;
  custom SQL skill created+enabled -> appears in get_active_chat_tools ->
  executes read-only via execute_chat_tool; SSRF guard blocks localhost/private;
  custom SQL rejects writes
- MCP: server create (cred redacted in list); test fails gracefully on unreachable
  host; seeded cached tool surfaces as namespaced visitor tool (allowed_for_velo);
  is_mcp_tool detection; delete
- Two real bugs caught + fixed: query_db(fetchone) returned [] not None (broke
  tenant_has_feature); custom-skill create ignored the enabled flag.
Unverified (needs live MCP server / OpenAI key): actual MCP tools/call round and
custom HTTP-skill live request; both are SSRF-guarded and unit-shaped here.
