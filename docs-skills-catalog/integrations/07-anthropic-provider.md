# Anthropic Provider (Claude Alongside OpenAI)

## When to use
You want admins to choose Claude per-agent (or use it as a fallback for specific capabilities), without making the rest of the codebase OpenAI-only. Useful when a particular agent benefits from Claude's strengths (long context, web search tool quality) or when a customer's billing/policy requires Anthropic.

## Architecture
- A single optional client (`anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)`) instantiated at module load if `ANTHROPIC_API_KEY` is set; `None` otherwise.
- The import itself is wrapped in `try/except` so the app boots even if the `anthropic` SDK isn't installed — keeps the dependency soft.
- Per-agent routing through an `agent_provider_settings` table — each agent selects a provider/model. Call sites read this row and dispatch to OpenAI vs Anthropic.
- Capability-level fallback: the `lookup_web_search` chat tool tries Brave first, and falls back to `_websearch_anthropic` which uses Claude's native `web_search_20250305` tool on `claude-sonnet-4-5`. The web-search call also writes to the cost ledger under the Anthropic provider so spend is visible.

Late-import / null-guard pattern: every Anthropic call site checks `if anthropic_client is None: return ...graceful error...` so missing creds degrade cleanly rather than 500.

## Data model
- `agent_provider_settings` — per-agent row holding provider name, model name, temperature, max_tokens, and any provider-specific extras.
- Cost ledger rows (`api_cost_events`) stamp `provider='anthropic'` and the actual model so spend splits cleanly from OpenAI in the cost dashboard.

## API surface
None of its own. Provider selection happens inside the chat/tool dispatchers.

## Key files
- `app.py` — `anthropic_client` setup (~line 582), `_websearch_anthropic` (~line 9932), Anthropic routing inside the chat tool loop (~line 10051).

## External deps
- `anthropic` Python SDK (soft import).
- `ANTHROPIC_API_KEY` env var.

## Pitfalls
- **Schemas differ.** Anthropic and OpenAI function-calling have *similar but not identical* tool-schema shapes; if you share tool definitions, convert at the boundary or maintain a translator.
- **Streaming protocols differ.** Don't try to share the SSE event-shape between providers — adapt at the dispatcher.
- **System prompts.** Anthropic puts the system prompt in a top-level `system` field, not inside `messages`. A copy-pasted OpenAI chat call will silently misbehave.
- **Token counting differs.** Don't reuse OpenAI tiktoken counts to estimate Anthropic cost; use Anthropic's own counter or accept post-hoc usage figures from the response.
- **Soft import means hidden runtime errors.** If `Anthropic = None` due to a missing dep, every dispatcher must check — easy to forget for a newly-added feature.

## Adaptation notes
- Generalizes to any multi-provider AI setup. Encapsulate dispatch in a `chat_complete(messages, agent_settings)` function and add a new branch per provider.
- Cost dashboard becomes meaningful when provider+model are stamped on each spend event.
- For web-search-quality comparisons, keep Brave as the primary (cheap, fast) and Anthropic as the fallback (richer but pricier).

## Adoption checklist
- [ ] Add `ANTHROPIC_API_KEY` to env management.
- [ ] Wrap the `from anthropic import Anthropic` in `try/except` so the app boots without the SDK.
- [ ] Instantiate the client only if the key is set; check `is None` at every call site.
- [ ] Add a provider column to the agent-settings table.
- [ ] Translate tool schemas at the dispatcher boundary.
- [ ] Stamp `provider` on every cost-ledger insert.
