# Markdown / JSON Chat Export

**Category:** Admin Tooling
**Related:** `admin-tooling/05-edit-and-rerun-chat-branch.md`

## When to use
Operators want to grab a finished AI conversation for an email,
a bug report, a fine-tuning dataset, or a customer record. Two
formats cover ~all uses: **Markdown** for humans (paste into Slack,
print to PDF) and **JSON** for machines (replay, fine-tune,
diff against a regression baseline).

## Architecture
- One endpoint: `GET /admin/api/chat/sessions/<id>/export?format=md|json`.
- Server-side:
  1. SELECT the session row + ordered `admin_chat_messages` rows.
  2. Branch on `format`:
     - `json` — return the raw rows as `{session: {...}, messages:
       [...]}` with `Content-Type: application/json` and a
       `Content-Disposition: attachment; filename="chat-<id>.json"`
       header so the browser downloads instead of rendering.
     - `md` — render a Markdown transcript: `# Title`, then per
       message a `**User**` / `**Assistant**` heading and the
       content. Code blocks fenced. Tool calls in a collapsed
       `<details>` block. `Content-Type: text/markdown;
       charset=utf-8`, same `attachment` header.
- Default to JSON if format param is missing/invalid — it's the
  lossless format and the safest default for an API.

## Data shape (JSON)
```
{
  "session": {
    "id": "uuid",
    "title": "...",
    "system_prompt": "...",
    "disabled_tools": [...],
    "created_at": "..."
  },
  "messages": [
    {"id": 1, "role": "user", "content": "...", "created_at": "..."},
    {"id": 2, "role": "assistant", "content": "...",
     "tool_calls": [{"name": "lookup_pricing", "args": {...},
                      "rows": N, "duration_ms": 42}]},
    ...
  ]
}
```

## API surface
- `GET /admin/api/chat/sessions/<session_id>/export?format=md|json`
  (`app.py:18580`).

## Key files
- `app.py:18580` — route
- `app.py:18582` — `admin_chat_session_export` implementation
- `app.py:1956` — `admin_chat_sessions` schema

## External deps
- None for JSON.
- For Markdown, stdlib only: escape backticks, fence code blocks,
  newline-normalise. No `markdown` package needed.

## Pitfalls
- **Strip secrets.** If your system prompt contains API keys, redact
  them in the export. If tool results contain customer PII you don't
  want forwarded, mask before serialising.
- **Set `Content-Disposition: attachment`.** Without it, Markdown
  renders as plain text in the browser tab — a footgun for non-techies.
- **Tool calls in Markdown** — long JSON blobs ruin readability. Wrap
  in `<details><summary>tool: lookup_pricing</summary>...</details>`
  so the transcript is human-scannable but the data is still there.
- **Filename safety** — `chat-{uuid}.json` is safe; user-supplied
  titles in a filename need sanitising (strip `/`, `\`, control
  chars).
- **Multi-MB conversations** — for very long sessions, stream the
  response (`stream_with_context`) and write rows one at a time so
  you don't materialise everything in memory.

## Adaptation notes
- **CSV export** for analytics use cases: one row per message with
  flattened token counts and tool-call summaries.
- **HTML export** with print CSS for "Save as PDF" workflows.
- **OpenAI fine-tune JSONL format** — same data, one
  `{"messages":[...]}` per line. Useful for "export this session as
  a training example" buttons.
- **Bulk export** — `/admin/api/chat/export?since=...&format=jsonl`
  for "download all conversations from May" use cases.

## Adoption checklist
1. Add the export route, branch on `?format=`.
2. Set `Content-Disposition: attachment; filename="..."` for both
   formats.
3. Mask any known-sensitive fields before serialising.
4. Add a "Download" dropdown in the admin chat UI offering both
   formats.
5. Document the JSON schema in your project README so downstream
   tools can rely on it.
