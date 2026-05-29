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
## Status: not_started   ## Branch: task/002-admin-core
