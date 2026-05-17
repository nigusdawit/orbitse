# Brave Search Tool (Web Search Exposed to the AI)

## When to use
The chat AI needs current-events / "look this up on the web" capability without the cost or complexity of a full agentic browsing tool. Brave Search has a generous free tier, simple REST API, and returns structured results suitable for an LLM to summarize directly.

## Architecture
A single helper function (`_websearch_brave`) wraps the Brave Search API. It's exposed to the AI as the `lookup_web_search` function-calling tool, the same shape as the other "lookup" tools in the chat loop (lookup_gallery_cards, lookup_services, etc.). When the LLM emits a tool call, the loop:

1. Calls Brave with the user-provided query.
2. Trims the response down to N top results with `title`, `url`, `snippet`.
3. Returns the trimmed JSON to the LLM as a `tool` message.
4. Logs the call (tool name, args, row count, duration) to `chat_messages.tool_calls_json` so admins can see what the AI searched for.

If Brave returns zero results or errors, the loop falls back to `_websearch_anthropic`, which uses Claude's native `web_search_20250305` tool (a different vendor, different quota, often complementary coverage).

## Data model
None. Each call is stateless; results aren't cached (queries are too varied to make caching pay off).

## API surface
- Tool name (to the LLM): `lookup_web_search`.
- Underlying HTTP: `GET https://api.search.brave.com/res/v1/web/search?q=...` with `X-Subscription-Token: <BRAVE_SEARCH_API_KEY>` header.

## Key files
- `app.py` — `_websearch_brave` (~line 9901), Brave endpoint URL (~line 9908), `lookup_web_search` tool registration (~line 10022).

## External deps
- `requests` (or `httpx`).
- `BRAVE_SEARCH_API_KEY` env var.

## Pitfalls
- **Rate limits on the free tier are tight** (~1 query/sec). Add a per-tenant or per-IP throttle if the AI may call it repeatedly in a tool loop.
- **Untrusted output goes straight to the LLM.** The snippets are attacker-controlled (a malicious site can prompt-inject). For high-stakes tools, scrub before passing.
- **No caching = repeated identical queries cost real money.** If your AI loop is verbose, add a tiny LRU keyed on the query string.
- **Quota exhaustion isn't fatal.** Wrap in try/except and let the fallback fire; the AI should never see a 500.
- **Country / safesearch defaults** are baked into the URL — make them configurable per tenant if you support multiple regions.

## Adaptation notes
- Same pattern works for any other search API (Tavily, Serper, Bing, Google Custom Search). Swap the URL and header; keep the function name `lookup_web_search` so the system prompt doesn't need to change.
- If you outgrow Brave's free tier, the dual-provider fallback (Brave → Anthropic native) already gives you graceful degradation.
- Surface "AI searched the web for: …" as a UI badge so the visitor can see which results informed the answer — better UX and clearer attribution.

## Adoption checklist
- [ ] Add `BRAVE_SEARCH_API_KEY` to the env manager whitelist.
- [ ] Write the wrapper: HTTP call, trim to N results, return JSON.
- [ ] Register it as a function-calling tool alongside your other lookups.
- [ ] Log to your tool-call audit so admins can see what was searched.
- [ ] Add a fallback path (Anthropic web_search or another provider) for empty / error results.
- [ ] Surface searches in the chat UI as a transparency badge.
