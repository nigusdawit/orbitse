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

**Why:** the voice path runs NO `lookup_*` agentic tool loop (it passes an empty
tool list to the model). So unlike the website chat, it can't pull business
detail on demand — anything the brain should know must be inlined into the voice
system prompt up front (catalog for awareness + RAG `lookup_knowledge_base` for
detail).

**How to apply:** when "voice doesn't know the business" but website chat does,
first prove the endpoint works (curl it with `Bearer VAPI_LLM_SECRET`, test BOTH
`stream:true` and `stream:false`, and check Vapi call `endedReason` — `customer-
ended-call` means the brain connected fine). Then compare what `api_chat` inlines
vs what `_vapi_llm_system_prompt()` inlines and close the gap. Keep the index
phrasing tool-free for voice (don't tell it to "call lookup_*"). Watch token
bloat: `build_site_index()` is inlined every turn on the voice path.

**Also:** the agentic ACTIONS (callback requests, etc.) are a separate concern —
they require tools DEFINED ON THE VAPI ASSISTANT pointing at `/webhooks/vapi`
(executed via `execute_chat_tool`), AND the bridge forwarding Vapi's tool list to
the model (it currently passes `[]`). Knowledge parity and action parity are two
independent fixes.

**Wrong assistant trap:** only a Vapi assistant whose `model.provider=custom-llm`
+ `url=<host>/api/vapi/llm` uses the app brain. "Managed" assistants
(provider=openai/anthropic) run their own dashboard-typed prompt with zero app
connection — testing with one of those looks like "the brain is broken."
