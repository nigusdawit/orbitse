# Persona Router

**Category:** AI / LLM Pipelines

## When to use
A single chat endpoint serves many distinct task types (content
editing, analytics, SEO, billing, design). One giant prompt + tool
list gives mediocre results everywhere; specializing per-persona
improves both quality and cost.

## Architecture
- A static `PERSONAS` registry. Each entry: `{name, system_prompt,
  allowed_tools, extra_tools, model?, temperature?}`.
- A tiny classifier function calls a cheap model (`gpt-4o-mini`) with
  the user message and the persona descriptions, returns the chosen
  key + a one-sentence reason. The reason is logged so admins can
  audit routing decisions.
- Per-request "persona override" sent as `persona` on the stream call
  — if present and valid, the classifier is skipped. In this codebase
  the pin is request-time only (the `/admin/api/chat/stream` handler
  reads `data.get("persona")` and passes it through as
  `persona_override`); the session row can additionally carry a
  `system_prompt_override` text field that layers on top regardless
  of which persona was chosen. To make the pin truly sticky across
  reloads, add a `pinned_persona` column to the session table and
  fall back to it when no per-request override is sent.
- The chat handler reads the persona, substitutes its system prompt,
  filters the tool list down to `allowed_tools ∪ extra_tools`, and
  runs the standard streaming tool-call loop.

## Data model
- `PERSONAS` dict in code (not a table — these are part of the app's
  capability surface).
- Per-session column (optional, for sticky pinning):
  `pinned_persona VARCHAR(40) NULL`. Not present in this codebase —
  the override is request-time. The session row DOES carry
  `system_prompt_override TEXT` for prompt-level pinning.
- Optional: log every routing decision to a `persona_routing_log`
  table for tuning.

## API surface
- Classification is internal (no public endpoint).
- The stream endpoint (`POST /admin/api/chat/stream`) accepts an
  optional `persona` field that overrides the classifier for that
  one call.

## Key files
- `app.py` — `ADMIN_CHAT_PERSONAS` (~line 16628),
  `_admin_classify_persona` (~16698), persona resolution inside
  `/admin/api/chat/stream`.

## External deps
- Any small cheap model for the classifier. Latency added: ~150–400 ms
  per first turn (skip for subsequent turns by caching the choice on
  the session).

## Pitfalls
- Don't let the classifier choose a persona that has access to a
  destructive tool the user didn't intend — keep destructive tools
  behind `propose_*` (see human-in-the-loop skill) regardless of
  persona.
- Two-tier model cost trap: classifying every single message wastes
  money. Cache the persona on the session and re-classify only on
  explicit user signal or large topic drift.
- A pinned persona that no longer exists in code (renamed/removed)
  must fall back gracefully — never crash the chat turn.
- Personas with overlapping tool sets create model confusion ("am I
  the analyst or the content editor?") — disjoint tool sets are
  clearer than maximally permissive ones.

## Adaptation notes
- The registry-in-code pattern is intentional: personas are part of
  the app's capabilities and reviewable in PRs. Making them DB-
  editable is possible but adds prompt-injection surface.
- For a visitor-facing single-purpose bot, one persona is fine; this
  pattern is most valuable for admin / power-user chats.

## Related skills
- `01-streaming-tool-call-loop.md` — the loop that runs once a
  persona is chosen.
- `07-parallel-subagents.md` — each spawned subagent can run under
  a different persona (and a constrained tool subset).
- `03-live-editable-system-prompts.md` — persona prompts are kept in
  code, but the per-session override still applies on top.
