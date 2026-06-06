---
name: Visitor chat tool-round budget & empty-reply invariant
description: Why the visitor /api/chat tool loop must end tool-less, and how the round budget is configured.
---

# Visitor concierge tool-call rounds

The visitor `/api/chat` SSE loop runs the model in rounds; a round ending in
`finish_reason=="tool_calls"` executes tools and loops again. If the model keeps
requesting tools every round it can exhaust the round budget **without ever
producing final text** → zero `token` SSE events.

**Invariant:** the loop's LAST allowed round must run with NO tools
(`_round_tools = [] if _round_idx == max_rounds - 1 else active_tools`) so the
model is forced to synthesize an answer. Without it, broad/vague questions
return an empty reply.

**Why it strands the UI:** the frontend (`public/script.js` chatSendStreaming)
clears its "thinking" indicator only on the FIRST `token` event. No tokens →
stuck on "thinking" forever. There is also a post-loop empty-reply safety net
that shows a retry message if a turn ends with no text/command/chips/page.

**Provider gotcha:** OpenAI rejects `tools=[]` with `tool_choice="auto"` —
`_stream_round_openai` must omit both when the tool list is empty. Claude's
helper already guards empty tools.

**Round budget (admin-controlled):** two super-admin AI Control knobs —
`visitor_max_tool_rounds` (normal, default 4) and
`visitor_max_tool_rounds_complex` (default 6, auto-applied to broad/
research-heavy questions detected by `_visitor_is_research_heavy`). Selected
budget is clamped to 1..12. Set the two equal to disable the auto-bump. Both are
in `_AI_INERT` at 4 so the AI master-kill reverts to the fixed pre-knob budget.

**How to apply:** any change to this loop (raising budgets, new providers,
refactors) must preserve BOTH the tool-less final round and the empty-list tool
guard, or many-tool turns silently break the chat UI.
