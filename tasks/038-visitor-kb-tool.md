# Task 038 — Visitor KB tool (audience-scoped retrieval) (Phase 6 / Epic B)

**Status:** done
**Branch:** task/038-visitor-kb-tool
**Depends on:** 036 (audience scoping)

## Goal
Give the VISITOR concierge a knowledge-base lookup tool that retrieves ONLY docs
scoped to the visitor ('visitor' or 'both'), making the 036 audience portal
actually do something for visitors.

## Acceptance criteria
- [x] `lookup_knowledge_base` visitor fn → rag.retrieve(surface="visitor");
      returns excerpts with source/page/score; never raises; []-on-empty.
- [x] Declared in CHAT_TOOLS (visitor schema) + CHAT_LOOKUP_FUNCTIONS dispatch.
- [x] Auto-registers as a skill (agent_skills) → super-admin toggles it in Skills;
      filtered by get_active_chat_tools like every other lookup.

## Test requirements
- [x] tool declared + dispatched; passes surface='visitor' (admin-only docs never
      returned); empty query → []; skill registered; visitor /api/chat still 200.

## Verification
4/4 tests vs embedded Postgres; byte-compile clean.

## Notes
Admin-only docs are never returned to the visitor (surface filter). The tool is
agent_skills-gated (Skills tab) — disable it to remove visitor RAG entirely.
Async ingestion + hybrid retrieval split into task 039 (kept this focused/safe).
