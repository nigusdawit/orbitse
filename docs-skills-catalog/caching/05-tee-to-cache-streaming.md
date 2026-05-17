# Buffer-While-Streaming TTS Cache (Pay for Generation Once, Stream Always)

## When to use
You proxy a paid streaming response (audio synthesis, video transcoding) and want the **first byte** to reach the client as fast as possible AND want subsequent identical requests to be free. You need atomic caching — partial / failed streams must never become a "hit" for the next caller — without the implementation overhead of teeing every chunk to disk.

## Architecture
A single request handler does both jobs in one pass:

1. Compute a content-addressed cache key from `(provider, voice, model, text)` (or whatever identity the asset has).
2. On cache hit, redirect the client to the persisted file URL.
3. On miss, open a streaming connection to the provider and an in-memory `io.BytesIO` buffer.
4. For each chunk received from the provider: **yield it to the client AND append it to the buffer** in the same loop. The client sees bytes in real time; the buffer accumulates the full response in parallel.
5. On clean stream completion, upload the buffer's contents to permanent storage as a single atomic write (`storage.get_storage().write_bytes(cache_subpath, buf.getvalue(), ...)`). Either the whole asset lands in cache or nothing does — by virtue of being one write call, there's no half-written state another reader can observe.
6. On client disconnect (`GeneratorExit`) or provider error, the buffer is simply discarded — no cache artifact is written, so the next request retries from scratch.
7. A cache-write failure after a successful stream is logged but **does not break playback**: the user already received their bytes. The next request just re-synthesizes.

Concurrent misses for the same cache key are harmless: each request builds its own in-memory buffer and uploads independently. Last writer wins on storage, which is fine — both produced identical bytes from identical inputs.

For TTS specifically, this is paired with a two-step browser flow:
- `POST /api/voice/tts/stream/prepare` — does the cache lookup. On hit, returns the cache URL. On miss, mints a one-shot signed token and returns the consume URL.
- `GET /api/voice/tts/stream/consume?token=...` — the `<audio>` element's `src`; this is where the buffer-while-streaming happens.

The split lets the cache-hit case do a cheap redirect without exposing a tokenless GET that anyone could fire to burn provider credit.

## Data model
None. The "cache" is the storage backend (filesystem or object store). Cache identity is a hashed subpath derived from the input tuple.

## API surface
- `POST /api/voice/tts/stream/prepare` — body specifies provider/voice/text. Returns `{stream_url: ..., cached: bool}`.
- `GET /api/voice/tts/stream/consume?token=...` — actual streaming endpoint.

## Key files
- `app.py` — `/api/voice/tts/stream/consume` route, `_stream_tts_openai`, `_stream_tts_elevenlabs` (search for `_stream_tts_openai` to locate). All three live near each other.

## External deps
The provider SDK (`openai.audio.speech.with_streaming_response.create(...).iter_bytes(...)`, `requests` with `stream=True` for ElevenLabs). A storage abstraction (`storage.get_storage().write_bytes(...)`) that backs onto the filesystem or an object store.

## Pitfalls
- **Memory cost is bounded by your input cap.** This pattern keeps the entire payload in RAM during the stream. Cap input length (TTS_MAX_CHARS in this codebase) so you can reason about per-worker memory under burst load. For very large assets (long video, multi-MB audio), switch to a `.part`-file-on-disk variant with `os.replace` for atomicity.
- **Open the streaming context OUTSIDE the generator** so configuration / auth errors (`OPENAI_API_KEY not set`, 401 from provider) raise *before* you've flushed response headers — once streaming starts you can't switch to a 500.
- **`GeneratorExit` is the client-disconnect signal.** Catch it, discard the buffer, re-raise. Don't try to recover.
- **Cache-write failure ≠ user-visible failure.** Wrap the storage call in `try/except` and log only — the user already has their bytes; the next caller will just re-synthesize.
- **Tokenized GET URL is one-shot for a reason.** A guessable or replayable URL on `/consume` lets an attacker burn your provider quota by spamming refresh.
- **Per-IP abuse cap belongs in `prepare`,** not `consume` — by the time `consume` runs you've already promised the provider you'd buy the stream.
- **gzip/brotli middleware in front will buffer.** Exclude these streaming endpoints from the compression whitelist (audio is already compressed; SSE would break if buffered).

## Adaptation notes
- For payloads too big for memory, swap `io.BytesIO()` for a unique-per-request `.part` file on disk and finish with `os.replace(tmp, final)`. Same atomicity guarantee, bounded memory, slightly more failure cleanup code (must `unlink` the `.part` on disconnect or error).
- The pattern generalizes to any provider with a streaming API: PDF rendering, image transcoding, etc.
- Cap cache size with an LRU sweep tick (the existing 30s tick scheduler is perfect for this).

## Adoption checklist
- [ ] Define the cache key tuple. Hash it into the storage subpath.
- [ ] Split the request into `prepare` (lookup + token mint) and `consume` (stream).
- [ ] In `consume`, open the streaming context outside the generator; build the buffer + yield chunks inside.
- [ ] Upload the full buffer to storage on clean completion; swallow upload failures (log only).
- [ ] Discard the buffer on `GeneratorExit` / exception — never write a partial.
- [ ] Exclude both endpoints from compression middleware.
- [ ] Add a per-IP rate limit on `prepare`.
- [ ] Periodically prune the cache by size or age.
