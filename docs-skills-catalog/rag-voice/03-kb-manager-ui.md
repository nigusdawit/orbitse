# Knowledge Base Manager UI (Upload · Status · Reindex · Citation Viewer)

**Category:** RAG · admin UX
**Status:** Production

## When to use
Your admins need a "drop files here, see them appear, see what the AI
quoted" surface for the RAG corpus. The UI also has to make tenant
scoping invisible (one tenant only sees their own files).

## Architecture
- A side-panel modal in the admin chat opens from a 📚 button.
- Five thin endpoints back the panel — all `@admin_required`, all
  tenant-scoped by the session's `tenant_id`:
  - `GET  /admin/api/kb/list`              — documents + counts/status.
  - `POST /admin/api/kb/upload`            — multipart, 25 MB cap,
    extension allowlist, runs `ingest_document` inline.
  - `DELETE /admin/api/kb/<doc_id>`        — tenant-scoped; 404 cross-tenant.
  - `POST /admin/api/kb/<doc_id>/reindex`  — force re-embed (admin
    replaced a file or wants to retry a previously failed parse).
  - `GET  /admin/api/kb/chunk/<chunk_id>`  — body for the citation
    viewer; returns `None`/404 cross-tenant.
  - `POST /admin/api/kb/preview`           — resolve a list of
    `[source: file p.N #id]` markers to their chunk bodies in one call.
- The chat stream emits a `kb_retrieval` SSE event listing the matched
  chunks; the renderer turns each `[source: …]` marker in the AI bubble
  into a clickable pill that opens the chunk viewer.

## Data model
Reuses `rag_documents` / `rag_chunks` (see `01`/`02`). The only UI-
specific column is `admin_chat_sessions.use_kb BOOLEAN DEFAULT TRUE` —
the per-session "Use Knowledge Base" toggle controlling auto-retrieve.

## API surface
| Method | Path                                | Purpose                       |
| ------ | ----------------------------------- | ----------------------------- |
| GET    | `/admin/api/kb/list`                | Documents + status            |
| POST   | `/admin/api/kb/upload`              | Multipart upload + ingest     |
| DELETE | `/admin/api/kb/<id>`                | Tenant-scoped delete          |
| POST   | `/admin/api/kb/<id>/reindex`        | Re-embed in place             |
| GET    | `/admin/api/kb/chunk/<id>`          | Single chunk body             |
| POST   | `/admin/api/kb/preview`             | Resolve N citation markers    |

## Key files
- `app.py` — routes `@app.route("/admin/api/kb/...")`.
- `templates/admin/dashboard.html` — modal markup, file picker, chunk
  viewer overlay, the `kb_retrieval` SSE handler in the chat renderer.
- `rag.py` — `list_documents`, `delete_document`, `get_chunk`.

## External deps
None beyond the RAG core (`02-document-ingest-and-chunker.md`) and the
admin auth decorator.

## Pitfalls
- **Tenant scoping on every call.** A copy-paste of one of these routes
  that forgets `WHERE tenant_id = …` becomes a cross-tenant data leak.
  The chunk and document helpers in `rag.py` enforce it; do not
  re-implement queries inline.
- **Extension allowlist is on the route, not the parser.** The
  parsers will happily accept disguised binaries — keep the allowlist
  check at the upload endpoint.
- **25 MB cap is server-side.** Set the matching `MAX_CONTENT_LENGTH`
  on Flask or your reverse proxy or large uploads die with an opaque
  413 before reaching the route.
- **Reindex inline blocks the request.** A 100-page PDF can take ~30 s;
  for very large files move to a background job (`messaging.register_tick`)
  and let the UI poll `status='indexing'`.
- **`kb_retrieval` SSE arrives before the agent bubble** — render order
  matters. The provided handler attaches the badge to the upcoming
  bubble, not the previous one.

## Adaptation notes
- Add a per-document `tags TEXT[]` column and a tag filter in the list
  view; pass `tags` into `retrieve` as an extra `WHERE tags && %s`.
- Add a "Replace file" button that calls `/upload` then `/reindex`
  with the new bytes — keeps the same `id` so existing citations don't
  break.
- For multi-user tenants, gate `delete` behind a role check (`admin`
  vs `viewer`) using the role primitives in `../auth/`.

## Related skills
- `01-pgvector-cosine-search.md`, `02-document-ingest-and-chunker.md`
- `../ai-pipelines/01-streaming-tool-call-loop.md` — `kb_retrieval` is
  fired from inside the streaming tool-call loop.
- `../auth/` — `@admin_required` + tenant resolution.
