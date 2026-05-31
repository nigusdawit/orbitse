# Task 039 — Async KB ingestion (Phase 6 / Epic B)

**Status:** done
**Branch:** task/039-rag-async
**Depends on:** 038

## Goal
Let big/bulk KB uploads ingest in the background so the upload request doesn't
block — gated, default-off (= prior inline behavior).

## Acceptance criteria
- [x] `async_ingestion_enabled` knob (config + AI Control "Knowledge Base" group,
      default False, env KB_ASYNC_INGESTION).
- [x] Shared `_kb_do_ingest(fname, data, mimetype, tenant_id)` helper (ingest +
      storage + storage_key/mtime patch), request-context-free.
- [x] Upload route: async ON → daemon thread + 202 {queued}; OFF → inline (200),
      identical to before. Frontend shows "Queued… indexing in background".
- [x] Master kill switch forces inline (async inert when AI enhancements off).

## Test requirements
- [x] inline default → 200 + doc row; async → 202 + thread creates the row;
      master-off forces inline (200).

## Verification
3/3 tests vs embedded Postgres; byte-compile + Jinja clean.

## Notes
Daemon thread; if a worker recycles mid-job the doc stays 'indexing' and the
existing reindex tick/button recovers it. Hybrid retrieval (vector+keyword RRF)
deferred to a follow-up; OCR is 039b.
