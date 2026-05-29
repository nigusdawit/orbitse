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
## Status: not_started   ## Branch: task/003-cost-skills-mcp
