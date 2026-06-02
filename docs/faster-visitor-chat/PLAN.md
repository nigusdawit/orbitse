# PLAN — Faster Visitor AI Chat

**Status:** APPROVED — 2026-06-02 · branch `task/079-faster-chat` · do NOT merge to `main` until manually verified + owner sign-off.
Detailed, code-grounded, adversarially-reviewed design lives in `./blueprint.md` (read it before editing). This file is the execution plan + the control surface.

## Goal
Make the public visitor chat (`POST /api/chat`) noticeably faster — latency is almost all prompt prefill of a ~19.7k-token context re-read on every model call (up to 4 rounds/message), while replies are tiny (15–90 tokens). Two layers:
1. **Phase 1 (everyone, behavior-preserving):** reorder the system prompt into a byte-stable cacheable prefix + dynamic suffix; make provider prompt caching actually take effect (Claude tools-block + stable system prefix; OpenAI automatic); trim the ~13.6k-token `SYSTEM_PROMPT` to ~10–11k. Re-reads the big fixed prefix at cache cost instead of full prefill.
2. **Phase 2 (optional, per-client, default OFF):** a hybrid router picks a specialist sub-prompt + tool subset so the model ingests only what it needs.

## Non-negotiable: PRESERVE TODAY'S BEHAVIOR AS THE DEFAULT
- Everything new is **additive, default-OFF/inert, and fail-open**. With the new controls at their defaults (the state of every existing client), the visitor chat behaves **exactly as today** — same answers, same tools, same site-control commands.
- Phase 1 only reorders/segments/caches/trims the SAME instruction + tool set, gated by a behavior-equivalence battery; the semantic answer cache (keys on the visitor message only) is untouched in both modes.
- Any router/classifier/cache error **falls back to the full default prompt + all tools** — chat never breaks.

## Control surface (operator controls EVERY new behavior)
**Per-client — Plans & Features (`_FEATURE_REGISTRY`, core.py):**
- `visitor_specialist_router` — **default OFF**. Per-client enable of the routed flow.

**Operator-wide — AI Control (`_ai_control_registry`, core.py; all under the `ai_enhancements_enabled` master kill; all default-inert):**
- `prompt_cache_enabled` — *(existing)* Phase-1 prompt caching on/off.
- `visitor_specialist_router_enabled` — **NEW bool, default OFF**. Operator master switch for the routed flow. Router activates only when this **AND** the per-client `visitor_specialist_router` flag are ON (and master-kill is on). Either off → today's flow.
- `visitor_specialist_router_model` — **NEW string, blank ⇒ gpt-4o-mini**. The cheap classifier's model.
- `visitor_specialist_embed_threshold` — **NEW float, default 0.78**. Confidence cutoff for the keyword/embedding match before falling back to the AI classifier.

Each NEW AI-control knob requires the 3 edit sites (registry row in `core.py` + dataclass field + constructor read in `pylego/config.py`) and an `_AI_INERT` entry so master-kill blanks it — see blueprint §3.3. **No migration** (AI settings + feature flags lazy-seed; prompts are rows).

**Editable prompts — AI Prompts tab (`_ai_prompt_registry`, core.py), category "Visitor Chat":**
- *(existing)* `visitor_system` — the base prompt (trimmed in Phase 1; token `{THEME_PLACEHOLDER}` still required).
- **NEW** `visitor_specialist_booking`, `visitor_specialist_pricing`, `visitor_specialist_general`, `visitor_specialist_leadcap` — the four specialist sub-prompts.
- **NEW** `visitor_specialist_router_prompt` — the classifier prompt (keep the `{options}` token).
- Each read via `get_prompt(key, DEFAULT_CONST)` (never the bare constant), registered like `persona_router`, with the 5 keys added to `tests/test_ai_prompts.py` `EXPECTED_KEYS` in registry order (the test asserts an exact ordered match — hard break otherwise).

## Execution phases (sequential — Phase 1 enables Phase 2)
- **P1a (commit 1):** message-assembly reorder → byte-stable prefix + dynamic suffix; Claude tools-block + system-prefix `cache_control`; **fail-open** retry around the Anthropic stream; OpenAI ordering; cache-hit telemetry (logs only). Behavior-preserving.
- **P1b (commit 2, separate + revertable):** trim `SYSTEM_PROMPT` (aggressive cut scoped to the generatePage design-system block only; **all command-syntax blocks fenced verbatim**), gated by the equivalence battery.
- **P2a:** add the `visitor_specialist_router` feature flag + the 3 new AI-control knobs + the 5 editable specialist/router prompt keys + the `_SPECIALIST_TOOLS` subsets. (Control scaffolding — inert until enabled.)
- **P2b:** the hybrid router by **extending `_visitor_apply_persona`** (keyword → embedding → tiny classifier, fail-open); the additive-safe tool narrowing (never drop custom/MCP skills); insert the specialist sub-prompt as a **separate system message before the per-turn reminder** (preserves the Phase-1 cache prefix AND keeps the reminder last); wire the branch in `generate()`; preserve semantic-cache + model routing in both modes. Also apply the same separate-system-message fix to the existing persona path (so its caching survives too).

## Top risks (from blueprint §6 — drive the implementation)
- **R1:** appending router text into `messages[0]` busts the prompt cache → insert a *separate* system message (after prefix, before reminder).
- **R2:** no fail-open around the Anthropic cache call → wrap + retry uncached once.
- **R3:** prompt-trim behavior shift → scope the cut, fence command blocks verbatim, separate revertable commit, temperature-0 eval gate.
- **R4:** tool-narrowing dropping custom/MCP skills → prune only known built-ins.
- **R5:** THEME relocation degrading generatePage theming on weak models → explicit forward-reference + manual A/B; fallback = keep theme in place, breakpoint before it.

## Verification (AUTOMATED RUNNER IS OFF FOR THIS — MANUAL)
- Automated (agent does): `ast.parse`; embedded-PG harness boots `import app`; full test suite shows **no new failures vs the 21 pre-existing baseline**; `tests/test_ai_prompts.py` updated + green; route table unchanged.
- **Manual (owner does, before merge):** exercise `/api/chat` on `$REPLIT_DEV_DOMAIN` — booking / pricing / FAQ / form-collection + the **generatePage theming A/B** + presentation mid-deck suppression, in both flag states; confirm cached-token usage (`[chat] cache read=…` logs + cost ledger) and the `[specialist] key=…` lines; confirm flag-OFF == today.

## Guardrails
- No Alembic migration (head stays 0030) unless a genuinely new column/table appears — none planned.
- Industry-agnostic language, heavy comments, modular.
- Branch only; never `main` without explicit owner OK after manual verification.
