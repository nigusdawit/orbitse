# OpenAI: Direct Client + Replit AI Proxy (Two Clients, Routed by Endpoint)

## When to use
You're on Replit (or any platform that offers a managed OpenAI proxy) and want the *cost / quota / billing* benefits of using the platform's proxy for chat/embeddings — but the proxy doesn't implement every OpenAI endpoint, notably `/audio/speech` (TTS) and `/audio/transcriptions` (Whisper STT). You need to route most traffic through the proxy and only the audio endpoints through a direct connection.

## Architecture
Maintain **two OpenAI client instances** at module load:

- `openai_client` — points at the proxy via `AI_INTEGRATIONS_OPENAI_BASE_URL` + `AI_INTEGRATIONS_OPENAI_API_KEY`. Used for: chat completions, embeddings, function-calling tool loop, anything the proxy supports.
- `openai_direct_client` — vanilla `OpenAI(api_key=OPENAI_API_KEY)` with no `base_url`. Used for: `audio.speech.with_streaming_response` (TTS), `audio.transcriptions.create` (STT), and any future endpoint the proxy doesn't ship.

Routing is by call site, not by feature flag — each module imports the one it needs. There's no auto-fallback; if the direct key is missing, voice features simply degrade with a clear error.

When neither set of credentials is present, both clients are `None` and call sites must check before use.

## Data model
None.

## API surface
None — just two named client objects exported from the app module.

## Key files
- `app.py` — `openai_client` (~line 553), `openai_direct_client` (~line 575). Voice endpoints import `openai_direct_client`; chat endpoints import `openai_client`.

## External deps
- `openai` Python SDK.
- Environment: `AI_INTEGRATIONS_OPENAI_API_KEY` + `AI_INTEGRATIONS_OPENAI_BASE_URL` for the proxy; `OPENAI_API_KEY` for direct.

## Pitfalls
- **Don't pass the proxy key to the direct client.** Proxy keys are usually scoped to the proxy hostname and will be rejected by api.openai.com.
- **Cost accounting splits.** Proxy traffic shows up in the platform's billing; direct traffic shows up in OpenAI's. Your cost dashboard needs to merge both.
- **Quota mismatch.** A burst of TTS requests doesn't deplete the proxy quota, so an alarm wired to "proxy spend" misses voice spend entirely.
- **One missing env var silently disables features.** Add a startup check that logs which clients are configured.
- **SDK version skew.** The proxy generally lags the SDK. New endpoints (e.g. `responses` API, `realtime`) may need to route via the direct client until the proxy catches up.

## Adaptation notes
- Pattern generalizes to any "managed proxy + occasional direct" arrangement (Azure OpenAI + direct OpenAI, Bedrock + direct Anthropic, etc.).
- If you grow a third destination, abstract behind a `client_for(endpoint_name)` factory rather than a third module global.
- Stamp every spend event with `provider="openai_proxy"` vs `"openai_direct"` so the cost dashboard can split the bill correctly.

## Adoption checklist
- [ ] Identify which OpenAI endpoints your platform's proxy supports.
- [ ] Create two clients at module load — proxy for the supported set, direct for the rest.
- [ ] Audit every `openai_client.` call and route audio calls to the direct client.
- [ ] Add a startup log line that prints which clients are configured.
- [ ] Update cost-accounting to tag rows with which client made the call.
