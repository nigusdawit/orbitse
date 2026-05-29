# Tasks — Admin/AI Platform Extraction

Master index. Detailed task files are fleshed out as each milestone is approached (downstream stubs
expand on first touch to avoid premature detail that drifts). See root `PLAN.md` for the overall plan.

| ID | Title | Status | Branch | Depends on | Parallel-with | Drift |
|----|-------|--------|--------|------------|---------------|-------|
| 000 | M0 — Scaffolding & shared infra | done | task/000-scaffolding-shared-infra | — | — | Module relocation deferred to consuming milestones |
| 001 | M1 — Visitor chat vertical slice | not_started | task/001-visitor-chat-slice | 000 | 002 | |
| 002 | M2 — Admin core | not_started | task/002-admin-core | 000 | 001 | |
| 003 | M3 — Cost + Skills/MCP | not_started | task/003-cost-skills-mcp | 002 | 004 | |
| 004 | M4 — RAG + Automations + Scraper | not_started | task/004-rag-automations-scraper | 002 | 003 | |
| 005 | M5 — Messaging + Reviews + Presentations | not_started | task/005-messaging-reviews-presentations | 003,004 | — | |
| 006 | M6 — Commerce + Tenancy + VELO | not_started | task/006-commerce-tenancy-velo | 005 | — | |
| 007 | M7 — Embed snippet + cross-origin widget | not_started | task/007-embed-widget | 001,006 | — | |
| 008 | M8 — WordPress plugin + SSO | not_started | task/008-wordpress-plugin | 007,002 | — | |
| 009 | M9 — Docs + final verify | not_started | task/009-docs-verify | 001-008 | — | |

**Status legend:** not_started | in_progress | paused | blocked | awaiting_review | done

**Concurrency note:** M1 and M2 touch disjoint files (visitor widget/chat vs admin shell) and can run
in parallel; M3 and M4 likewise. Everything depends on M0's shared infra landing first.
