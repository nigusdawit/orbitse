# Multi-Format Document Ingest + Token-Aware Chunker

**Category:** RAG · ingest
**Status:** Production

## When to use
You need to accept user-uploaded documents in mixed formats (PDF, DOCX,
PPTX, CSV, TXT) and turn them into embedded chunks for vector search,
without pulling in LangChain or a heavyweight ETL framework.

## Architecture
Three sequential pure-functional stages, each easy to test in isolation:

1. `extract_text(filename, data)` → `[(page_number, text), …]`. One
   branch per extension. PDF and PPTX yield real page/slide numbers;
   DOCX, CSV, TXT yield a single `(1, full_text)` pair.
2. `chunk_pages(pages, target_tokens=800, overlap=100)` → list of dicts
   `{chunk_index, page_number, text, token_count}`. Word-based sliding
   window using `words / 0.75 ≈ tokens` (no `tiktoken` dependency).
3. `embed_batch(texts)` → `[vector(1536)]` via OpenAI
   `text-embedding-3-small`, batched 100 at a time, recording one
   `rag_embed` cost-event per batch.

Each format degrades gracefully: a missing optional dep returns a
placeholder string instead of raising, and a scanned (image-only) PDF
yields zero chunks but no error.

## Data model
Produces rows for `rag_chunks` (see `01-pgvector-cosine-search.md`).
`rag_documents` carries one row per uploaded file with `status` in
`indexing | ready | empty | failed`, `chunk_count`, `page_count`,
an error column, and `source_mtime` so the reindex tick can detect
edits-in-place.

> NOTE: the 0005 migration declares the error column as
> `error_message` but `rag.py` writes to `error_text`. One of them is
> wrong on the current branch — pick a name and align both before
> porting. The blueprint stays agnostic about which name wins.

## API surface
- `rag.ingest_document(filename, data, tenant_id, session_id)` — full
  pipeline; returns the new document id. Wraps every stage in
  `try/except` so a bad file ends up `status='failed'` with a readable
  `error_text` instead of a 500.
- `rag.reindex_document(doc_id, filename, data, session_id)` — same
  thing without creating a new row; deletes the old chunks first.
- `rag.reindex_tick(read_file_bytes)` — scheduler tick, throttled to
  every 6 h per process, re-indexes any document whose stored
  `source_mtime` changed.

## Key files
- `rag.py` — extractors `_extract_pdf/_docx/_pptx/_csv/_txt`,
  `chunk_pages`, `embed_batch`, `ingest_document`, `reindex_tick`.
- `requirements.txt` — pinned `pypdf`, `python-docx`, `python-pptx`.

## External deps
- `pypdf` (PDF), `python-docx` (DOCX), `python-pptx` (PPTX). CSV/TXT
  use only the stdlib. All three are imported lazily inside the
  extractor so a missing package only breaks the matching format.
- OpenAI embeddings endpoint (or any 1536-dim equivalent).

## Pitfalls
- **Image-only PDFs return empty text.** You must surface this in the
  upload UI (`status='empty'`) or admins will think the document is
  searchable when it is not.
- **Word/token approximation under-counts.** `len(words) / 0.75` is a
  rule of thumb; non-English prose can blow the embedder's 8191-token
  per-input limit. Either install `tiktoken` and switch to a real
  encoder, or cap `target_tokens` lower (e.g. 600) for safety.
- **CSV column-value rendering is naive.** `col: val | col: val …` per
  row works for short rows; very wide tables produce long single-line
  chunks that embed poorly. Pre-process big CSVs.
- **No virus scan.** The 25 MB cap is the only hard limit; pair this
  with an extension allowlist on the route (`SUPPORTED_EXTS`) and
  consider ClamAV in production.
- **Reindex tick is in-process state.** A process restart re-checks
  immediately; multiple workers each run their own throttle.

## Adaptation notes
- Add a new format by adding `_extract_<ext>(data) -> [(page, text)]`
  and an entry in `SUPPORTED_EXTS`. The rest of the pipeline is
  format-agnostic.
- Replace OpenAI embeddings with any provider by swapping `embed_batch`
  — keep the function signature `List[str] -> List[List[float]]`.
- For OCR over scanned PDFs, branch in `_extract_pdf`: if
  `extract_text()` returns empty for a page, hand the page bitmap to
  Tesseract or a vision-LLM and stitch the OCR text back into the
  `(page_no, text)` tuple.

## Related skills
- `01-pgvector-cosine-search.md` — query side that consumes these rows.
- `03-kb-manager-ui.md` — upload/reindex/delete admin surface.
- `../ai-pipelines/01-streaming-tool-call-loop.md` — the host loop that
  calls `lookup_knowledge_base` against the indexed chunks.
