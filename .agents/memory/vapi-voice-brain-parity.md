---
name: Vapi voice brain must mirror website chat's business-awareness blocks
description: Why the Vapi custom-LLM voice agent gives generic answers, and what its prompt builder must include to match the website concierge.
---

# Vapi voice brain ↔ website chat prompt parity

The Vapi custom-LLM bridge (`/api/vapi/llm/chat/completions`) does NOT reuse the
website chat's prompt assembly. It builds its own system prompt in
`_vapi_llm_system_prompt()`. The website chat (`api_chat`) inlines several
business-awareness blocks (SITE IDENTITY from `site_settings`, and the SITE INDEX
from `build_site_index()` — the names/slugs catalog of services/experiences/
gallery/pricing). If those blocks are missing from the voice builder, the voice
agent answers **generically** (invents made-up services) even though the website
chat answers correctly — both supposedly "share the concierge prompt."

**Why (historical):** the voice path used to run NO agentic tool loop (it passed
an empty tool list to the model), so anything the brain should know had to be
inlined up front. That is now only HALF true — the bridge runs a bounded tool
loop (see "Action parity" below), so `lookup_*` tools CAN be called on demand. The
inlined catalog still matters for instant awareness / low latency (avoids a tool
round just to know what services exist), so keep inlining it.

**How to apply:** when "voice doesn't know the business" but website chat does,
first prove the endpoint works (curl it with `Bearer VAPI_LLM_SECRET`, test BOTH
`stream:true` and `stream:false`, and check Vapi call `endedReason` — `customer-
ended-call` means the brain connected fine). Then compare what `api_chat` inlines
vs what `_vapi_llm_system_prompt()` inlines and close the gap. Keep the index
phrasing tool-free for voice (don't tell it to "call lookup_*"). Watch token
bloat: `build_site_index()` is inlined every turn on the voice path.

**Action parity (DONE):** the bridge `_round()` now runs a bounded in-process tool
loop (max 3 rounds) over `get_active_chat_tools(audience="velo")` and executes each
call via `execute_chat_tool(name, args, session_id=call_id)` — so callback/lead/
meeting requests are actually written, not just spoken. Tool calls run silently;
spoken tokens stream live; the LAST round is forced tool-less (the visitor
last-round-tool-less invariant) so a tool-happy turn never strands the call.
Fail-open: if the tool inventory can't load, `_voice_tools=[]` → plain Q&A (the old
behavior). **Two gates still apply per action:** `agent_skills.enabled` (tool
visibility) AND the per-action `*_enabled` AI-Control knob (execution; e.g.
`callback_requests_enabled`, `meetings_enabled` default OFF) — a disabled action
returns a friendly "not available" string, it does not error. CHAT_TOOLS holds ONLY
data-lookups + actions (no site-control tools), so this is safe over voice; you do
NOT need tools defined on the Vapi assistant for this in-process path. **Why:**
passing `[]` tools meant the model could only describe an action and nothing saved.

**Caching contract:** the voice prompt builder returns a `(stable_prefix,
volatile_suffix)` pair so prompt caching can re-use the static block. Stable =
base + site identity + site index + brand voice + scope/safety/escalation + voice
note (identical across turns AND calls). Volatile = per-turn RAG + per-call CALL
CONTEXT — these MUST stay out of the prefix or they bust the cache every turn.
Pass to Claude as a LIST `[prefix, suffix]` (cache_control lands on part 0 only);
to OpenAI as two ordered system messages (stable first) for automatic prefix
caching. **Why:** a single concatenated string with volatile RAG embedded gives a
cache MISS every turn on Claude. Caching only fires when the `prompt_cache_enabled`
AI-Control knob is on (Anthropic); OpenAI auto-caches regardless.

**Wrong assistant trap:** only a Vapi assistant whose `model.provider=custom-llm`
+ `url=<host>/api/vapi/llm` uses the app brain. "Managed" assistants
(provider=openai/anthropic) run their own dashboard-typed prompt with zero app
connection — testing with one of those looks like "the brain is broken."
