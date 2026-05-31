# Task 036 — RAG document audience scoping + portal (Phase 6 / Epic B)

**Status:** done
**Branch:** task/036-rag-audience
**Depends on:** 034

## Goal
Let the super admin scope each KB document to an AI audience (visitor | admin |
both), so RAG retrieval is filtered per surface. Plan: PLAN_VISITOR_AI / roadmap.

## Acceptance criteria
- [x] rag_documents.audience column (migration 0011; default 'both'; alembic-owned).
- [x] rag.retrieve(surface=) filters by audience ('admin'→admin+both,
      'visitor'→visitor+both, None→no filter/back-compat); rag.set_audience helper
      (validated, tenant-scoped); list_documents returns audience.
- [x] Admin retrieve call sites tagged surface='admin' (admin tool, chat
      auto-injection, kb preview).
- [x] PUT /admin/api/kb/<id>/audience (super-admin) + Knowledge tab "Used by"
      dropdown per doc.

## Test requirements
- [x] audience column + default; set_audience validate/tenant-scope; route
      super-admin 200 / invalid 400 / 404 / client 403; list returns audience.

## Verification
4/4 tests vs embedded PG; alembic head 0011; byte-compile + Jinja clean.

## Notes
The VISITOR agent has no KB tool yet (RAG was admin-only in the monolith), so
'visitor'/'both' docs are dormant until the visitor KB retrieval lands (next Epic
B task). This task ships the scoping infrastructure + portal so docs can be
pre-classified. Retrieve audience-filter SQL not E2E'd in-sandbox (embedding key
absent); covered by inspection + the helper/route tests.
