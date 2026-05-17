# Multi-Modal Chat Input (Image + Document Attachments)

**Category:** AI / LLM Pipelines

## When to use
The chat surface needs to accept screenshots, photos, PDFs, slides,
spreadsheets, etc. Images should reach a vision-capable model as
proper `image_url` parts; documents should be extracted to text and
injected as a transient context block for the next turn.

## Architecture
- **Two-step upload:** the client uploads attachments BEFORE sending
  the message. Each upload returns an `attachment_id`. The chat
  `send` call then passes `attachment_ids: [...]` alongside the text
  message.
- **Upload endpoint** (`POST /admin/api/chat/attachments/upload`,
  multipart) does an ext + browser-reported MIME check against an
  allowlist, enforces a byte size cap, writes the blob to the storage
  layer under `admin_chat_attachments/<session_id>/<uuid>.<ext>`,
  and inserts one `admin_chat_attachments` row with `storage_key`
  and `extracted_text` (for documents). Returns
  `{id, kind, filename, mime, size, text_preview}`. Thumbnails are
  rendered on demand by a separate route, not at upload time.
- **Thumbnail endpoint** (`GET /admin/api/chat/attachments/<id>/thumb`)
  renders/serves a thumbnail when the chat history needs to show a
  chip. Keeps the upload hot path cheap.
- **Document extraction** at upload time (pypdf / python-docx /
  python-pptx / csv stdlib via the shared `rag.extract_text`) is
  cached on the row so it isn't re-run per chat turn. Capped at
  200K chars.
- **Assembly into the next turn:**
  - For each attachment matching a vision MIME (`image/*`), append an
    `{type: "image_url", image_url: {url: <signed/served URL>}}` part
    to the user message content.
  - For each document attachment, prepend a transient
    `{role: "system", content: "[attached file: <name>]\n<extracted
    text, truncated>"}` block, NOT persisted into history (the
    `attachment_ids_json` snapshot on the message row is enough to
    rehydrate later).
- **Rehydration on `/history` reload:** the message row carries
  `attachment_ids_json`; the frontend renders thumbnail chips on the
  user bubble and refetches storage URLs as needed.
- Drag-and-drop on the composer triggers the same upload flow.

## Data model
- `admin_chat_attachments (id, tenant_id, session_id, message_id,
  kind, filename, mime, size_bytes, storage_key, thumbnail_key,
  extracted_text, created_at)`. `message_id` is NULL until the next
  turn persists.
- `admin_chat_messages.attachment_ids_json JSONB` — per-message
  snapshot for rehydration.

## API surface
- `POST /admin/api/chat/attachments/upload` — multipart `file` +
  `session_id`, returns `{id, kind, filename, mime, size,
  text_preview}`.
- `GET /admin/api/chat/attachments/<id>/thumb` — on-demand thumbnail.
- `POST /admin/api/chat/stream` accepts `attachment_ids: [...]`.
- No DELETE endpoint exists in this codebase — orphan cleanup is
  done by a periodic sweep (add an explicit DELETE for an "x" button
  on uncommitted uploads when porting).

## Key files
- `app.py` — `admin_chat_attachments` schema (~line 3713), upload /
  stream / delete routes, vision-part assembly in the chat handler.

## External deps
- Pillow (image thumbnails), pypdf / python-docx / python-pptx / csv
  stdlib (text extraction). A vision-capable model (gpt-4o, claude-3.5,
  gemini-1.5) for the image path.

## Pitfalls
- Sniff MIME from BYTES, not just the uploaded filename — trusting
  `Content-Type` from the browser is a classic upload bypass.
- Cap document text injection (e.g. 25 KB) — a 500-page PDF would
  blow the context window. Truncate with an explicit
  `[truncated, N more pages]` marker so the model knows.
- Storage URLs: if you serve from disk, gate them behind the admin
  session; if from object storage, use signed URLs with short TTL.
- Orphan cleanup: an upload that's never attached to a message
  (browser tab closed) lingers — run a periodic sweep that deletes
  rows + storage where `message_id IS NULL AND created_at < now() -
  interval '24 hours'`.
- Vision input bills per image at the provider — surface the cost in
  the same ledger pattern used for chat tokens (see related skills).
- Don't persist the extracted document text into the chat history —
  it bloats every subsequent turn's prompt. Treat it as transient.

## Adaptation notes
- For visitor (non-admin) chat, the same pattern works but tighten
  size/count caps aggressively and consider sandboxing untrusted
  documents.
- Server-side OCR (Tesseract) extends this to scanned PDFs but adds
  significant latency — make it opt-in.

## Related skills
- `01-streaming-tool-call-loop.md` — the consumer of the assembled
  multimodal message.
- `../rag-voice/` (Batch 3) — for persistent document indexing
  (vs. transient per-turn injection).
- `../auth/03-admin-gate.md` — the upload/delete endpoints all sit
  behind the admin gate.
