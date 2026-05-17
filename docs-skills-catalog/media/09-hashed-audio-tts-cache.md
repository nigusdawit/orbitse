# Hashed audio / TTS disk cache

## When to use
Anywhere you pay per-character (or per-request) for media generation that:
- has expensive provider calls (TTS, image gen, video clips),
- often produces the same output for the same input (greetings, error phrases, fixed system replies),
- can safely be served from any byte-identical source (no per-user personalisation in the bytes).

A content-addressed disk cache turns repeat plays into zero-cost file reads while still letting first-time text fall through to the provider.

## Architecture
Cache key is a SHA-256 of the tuple `(provider, voice, model, text)` — every input that could change the output bytes goes into the hash. The hash becomes the filename: `uploads/voice/<hash>.mp3`.

Per-request flow:
1. Compute `hash = sha256(f"{provider}|{voice}|{model}|{text}".encode()).hexdigest()`.
2. Build subpath `voice/<hash>.mp3`.
3. Check `storage.exists(subpath)` — if HIT, return the cached URL (free).
4. If MISS, enforce per-IP daily char cap (`_check_tts_budget`, default 30,000 chars/IP/day) → 429 on overflow.
5. Call the provider, atomically write bytes to `voice/<hash>.mp3.part-<request_id>` then `os.replace` to the final key (see the atomic-write skill).
6. Stamp a `voice_cost_events` row with the stamped per-million-chars price so historical cost can never drift after a price edit.
7. Return the cached URL.

For streaming TTS (where the visitor must hear the first words within ~1 s), the same hash addressing applies: the streaming consume endpoint tees the provider bytes to a unique `.part` file while piping them to the client, and promotes the `.part` to the final cache key only on clean EOF. Disconnect or provider error → `.part` removed, next request re-generates cleanly.

Per-IP daily char cap (30 k by default) protects against abuse: an attacker can't fill the cache with garbage that never repeats, and you don't pay unbounded provider bills before the cost cap surface catches up.

## Data model
- Cache files: `voice/<sha256-hex>.mp3` (or `.<ext>` per provider).
- `voice_cost_events` — `provider`, `voice`, `model`, `chars`, `unit_price_per_million_chars`, `cost_cents`, `created_at` (see analytics catalog → cost-transparency skill for the full ledger pattern).
- Per-IP counter for the daily cap (in-process dict is enough; resets on restart, fine for anti-abuse).

## API surface
HTTP:
- `POST /api/voice/tts` — legacy one-shot generation (admin pre-warm).
- `POST /api/voice/tts/stream/prepare` — returns either a cache-hit URL or a tokenised one-shot consume URL.
- `GET /api/voice/tts/stream/consume?token=...` — pipes provider bytes to the client and tees to the cache.

Programmatic:
- `_generate_tts_audio(provider, voice, model, text)` — computes the hash, checks the cache, calls the provider, writes the file.

## Key files
- `app.py:27981` — `_generate_tts_audio()` (cache-key construction + provider dispatch).
- `app.py:27800` — `_check_tts_budget()` per-IP daily char cap.
- `app.py` (TTS stream consume route) — atomic `.part` cache promotion.

## External deps
- `hashlib` (stdlib) — SHA-256 keying.
- The TTS providers themselves (OpenAI `/audio/speech`, ElevenLabs streaming endpoint).
- The pluggable storage layer for disk vs S3 placement (see storage skill).

## Pitfalls
- **Hash EVERY input that affects bytes.** Forgetting `model` (or `voice` for multi-voice providers) silently serves wrong audio. Putting `text` in but not `voice` is the classic bug.
- **Don't put per-user data in the hashed text** unless you actually want a per-user cache entry; greetings like "Hi {name}" generate a unique cache file per visitor and the hit rate plummets.
- Cache files survive deploys only if storage is durable — on Replit's ephemeral FS, flip to S3 (see storage skill) or accept regeneration after every redeploy.
- The per-IP cap is anti-abuse, not billing — pair it with the cost-cap surface for real-money limits.
- Always atomically write (`.part` → `os.replace`) so a disconnect during generation can't leave a truncated MP3 in the cache that subsequent requests will happily serve.
- Stamp the unit price at write time on the cost-event row; a later price edit must not retroactively rewrite history.

## Adaptation notes
- Same pattern works for image generation, sound effects, and any other deterministic provider call.
- For very large caches, add a periodic LRU sweep keyed on file mtime — but only after measuring; cheap MP3s compress so well that 50 k entries are still well under a GB.
- To share cache across regions, place the file on S3 and let CloudFront / equivalent serve it directly.

## Adoption checklist
- [ ] Decide the cache-key tuple — list every input that affects the bytes.
- [ ] Use SHA-256 (not MD5 — cheap, collision-resistant, plenty fast).
- [ ] Place files under a dedicated subpath (`voice/`, `images/`) so the storage convention stays clean.
- [ ] Wire the per-IP cap and pair it with the cost-cap surface.
- [ ] Use atomic writes — never expose a partially-written file under a cache key.
- [ ] Stamp cost-event rows at generation time with the price-then-current.
