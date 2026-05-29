# Task 002 — M2: Admin core

## Goal
Admin dashboard shell (only the IN tabs), admin AI chat (streaming + sessions + branch/export +
pending-action approval flow), provider settings, chat history, generated-pages admin.

## Acceptance criteria (to expand on first touch)
- [ ] `admin/dashboard.html` rebuilt with IN tabs only; `admin/login.html`; `ADMIN_MODE` gating.
- [ ] `blueprints/admin_chat.py` (`/admin/api/chat/*` + action approve/reject).
- [ ] `blueprints/provider.py` (`/admin/api/llm-provider`, chatbot-settings, default-system-prompt).
- [ ] Chat history + generated-pages admin endpoints.

## Test requirements (to expand)
- pytest route tests for admin_chat send/stream/session; approval gate blocks mutation until approved.
- `verify`: `/admin` renders, chat works, no console errors.

## Dependencies: 000   ## Parallel-with: 001
## Status: done (merged)   ## Branch: task/002-admin-core

## Verification (embedded-Postgres gate, 47/47 green)
- admin auth: 401 when anon, /admin redirects to login, bad pw rejected, login sets
  session, /admin serves dashboard when authed
- provider get/put roundtrip (openai<->claude); chatbot-settings persist; default prompt
- chat-history list/detail; generated-pages list/PUT-status/DELETE
- admin tools: SELECT-only guard (rejects write + multi-statement), non-writable table
  blocked, propose->park (nothing written)->approve writes->re-approve 409, reject preserves
- ruff clean; unit suite green
Unverified (needs OpenAI key): the admin chat LLM token stream itself. The tool dispatch +
approval machinery (the risky part) is fully DB-verified.
