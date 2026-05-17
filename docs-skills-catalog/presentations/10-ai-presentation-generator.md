# AI Presentation Generator (Narrated Slide Decks with TTS Voiceovers)

## When to use
A visitor says "walk me through your offerings" or "tell me about the wedding venue" and the answer is genuinely a 6-slide story — title slide, three feature slides with hero images, a pricing slide, a CTA — not a chat reply, not a single generated page. You want the AI to surface a saved deck OR generate one inline, then play it back full-screen with the AI's voice narrating each slide while the visitor watches.

## Architecture
Two tables hold deck content; a third surface (the chat) launches the playback:

- `presentations(id, slug UNIQUE, title, description, display_mode, ai_narrate_mode, enabled, …)` — one row per deck. `display_mode` controls the visual template (`rich`, `minimal`, etc.). `ai_narrate_mode` is one of two values: `manual` (use whatever was saved into `narration_text` on each slide) or `auto` (regenerate narration on demand via the `/admin/api/presentations/<id>/generate-narration` route). Any other value falls back to `manual`.
- `presentation_slides(id, presentation_id FK ON DELETE CASCADE, order_index, title, body, image_url, narration_text)` — one row per slide.

Delivery path: **saved decks only.** The admin Presentations tab supports building slides by hand AND a "PowerPoint/PDF import" route that extracts slide images + speaker notes. The AI knows about saved decks via the `lookup_presentation` tool (see the streaming tool-call loop skill); when the AI decides a saved deck is the right answer it emits an action like `{"action":"start_presentation","slug":"…"}` in a fenced ```command``` block. There is no inline "generate a brand-new deck from scratch in chat" action — the deck must exist in the database first. A common convenience: when only one deck is enabled site-wide and the visitor asks something deck-shaped, the backend auto-synthesizes the `start_presentation` command with that deck's slug (see `app.py` ~line 20018).

When the player mounts, it iterates slides in `order_index`:
1. Render the slide visual (image + title + body) with theme tokens.
2. For each slide, fetch `/api/voice/tts/stream/prepare` with the slide's `narration_text`, then play the returned audio URL through a plain `<audio>` element. This is the same streaming TTS *endpoint* the chat uses, but the player does NOT go through `VoiceAgent.streamSpeakBegin/Feed/End` — that streamer is the sentence-by-sentence in-chat path, while slide narration is already a complete pre-written sentence per slide, so one prepare+play per slide is enough.
3. Auto-advance as soon as the per-slide TTS audio fires its `onended` event (current behavior — there is no minimum-dwell timer; if audio is short or autoplay is blocked, the visitor relies on the manual controls).
4. Player controls are prev / next / pause buttons — there is no draggable scrubber/timeline. Pause toggles the underlying `<audio>` element.

The same TTS audio cache as the chat applies — repeat plays of a popular saved deck cost zero TTS dollars after the first viewer.

The chat session captures the launch event so transcripts log "AI played presentation: <slug>" with the deck title.

## Data model
- `presentations(id SERIAL PK, slug UNIQUE, title, description, display_mode, ai_narrate_mode, enabled, created_at, updated_at)`
- `presentation_slides(id SERIAL PK, presentation_id INT REFERENCES presentations(id) ON DELETE CASCADE, order_index INT, title TEXT, body TEXT, image_url TEXT, narration_text TEXT)` — indexed `(presentation_id, order_index)`.

## API surface
Public:
- `GET /api/presentations/<slug>` — fetch one deck (enabled-only). There is no public list route — the AI gets its catalog through the `lookup_presentation` tool that hits the DB server-side, not via a public listing.

Admin:
- `GET/POST /admin/api/presentations`, `GET/PUT/DELETE /admin/api/presentations/<id>` — CRUD.
- `POST /admin/api/presentations/<id>/slides` — per-slide CRUD.
- `POST /admin/api/presentations/import` — PDF/PPTX import.
- `POST /admin/api/presentations/<id>/generate-narration` — backfill `narration_text` via an LLM call.

Chat-time:
- The AI emits `{"action":"start_presentation","slug":"…"}` in a fenced ```command``` block; the frontend's `case 'start_presentation'` handler in `public/script.js` opens the player.
- TTS goes through the shared streaming pipeline: `POST /api/voice/tts/stream/prepare` then `GET /api/voice/tts/stream/consume?token=…`.

## Key files
- `app.py` — `presentations` + `presentation_slides` table init (~line 1835), all admin CRUD routes (~line 20396+), public `GET /api/presentations/<slug>` (~line 21382), `lookup_presentation` tool, the `start_presentation` synthesis path (~line 19933+), and the PDF/PPTX import routes (~line 20622, 20731, 20821).
- `public/script.js` — presentation player and `case 'start_presentation'` dispatcher (~line 7524) with race-guard for back-to-back launches.
- `public/voice.js` — exposes the shared `/api/voice/tts/stream/prepare` + `/consume` helpers (the chat-side `streamSpeakBegin/Feed/End/Cancel` API lives here too but the presentation player doesn't go through it).
- `templates/admin/dashboard.html` — Presentations tab with slide builder, narration editor, and PPTX/PDF import.

## External deps
- **PyMuPDF** (imported as `fitz`) for PDF slide-image extraction — renders each PDF page at 2× scale via `fitz.Matrix(2.0, 2.0)` so the slide stays sharp on retina screens. Not `pdf2image`/Poppler.
- **Pillow** (`PIL.Image`) for the post-extraction image handling.
- **`python-pptx`** for PowerPoint import (slide text + speaker notes → `narration_text`).
- OpenAI/ElevenLabs TTS for narration playback (shared with chat).

## Pitfalls
- **Auto-advance vs. user control.** Current player advances the instant the slide's audio `onended` fires — there is no min-dwell guard, so very short narrations can flip slides faster than a visitor can read them. Mitigations to consider: pad narration text to a minimum length at generation time, or add a JS timer that delays the auto-advance until `max(audio_end, min_dwell_ms)`.
- **First-slide TTS latency.** Even with streaming TTS, the first slide can have ~800ms of dead air. Pre-warm by firing `/prepare` for slide 1 the moment the player mounts, and for slide N+1 the moment slide N starts playing.
- **`ai_narrate_mode='auto'` is an admin-side regenerate, not a per-play live-narration loop.** It exists so the admin can backfill narration after editing slide titles/bodies without writing scripts. Per-slide LLM calls during playback are intentionally not implemented — they would stall playback if the LLM API is slow. If you add that, use a per-slide timeout and fall back to the stored `narration_text`.
- **PPTX import is lossy.** Slide notes are extracted into `narration_text` by default; if the deck has no speaker notes, you have to either generate narration with an LLM at import time or leave narration blank (and the player will silently skip TTS for those slides — surface that to the admin).
- **`ON DELETE CASCADE`** on `presentation_slides` is essential — without it, deleting a deck leaves orphan slide rows that breach FK assumptions elsewhere.
- **Fuzzy slug resolution** is a footgun in admin previews: editing a draft slug to "test" might fuzzy-match a real published slug. Disable fuzzy fallback for admin GETs.
- **Background music + TTS** double-stack audio. If you ship background tracks, duck them to ~15% volume during narration.

## Adaptation notes
- For a "branded deck export" feature, render the same player into a recorder (`MediaRecorder` API) so admins can download a narrated video — the cache hits make this fast.
- The same player + TTS pipeline drives **product walkthroughs** and **onboarding tours**; only the data source changes.
- A "save chat as presentation" pin lets visitors convert a particularly useful AI answer into a permanent deck — write the inline `generatePresentation` slides into the `presentations` + `presentation_slides` tables.
- Multi-tenant: scope `presentations.slug` by tenant_id (composite UNIQUE) so two tenants can both have a `welcome` deck.

## Adoption checklist
- [ ] Create `presentations` + `presentation_slides` with `ON DELETE CASCADE`.
- [ ] Build admin CRUD UI + a PPTX/PDF import that populates slides and pulls speaker notes as initial narration.
- [ ] Implement the `lookup_presentation` AI tool so the chat can find decks by name/topic.
- [ ] Add the `start_presentation` action to the streaming dispatcher (single action, slug-based).
- [ ] Build the player UI: slide renderer + auto-advance on audio `onended` + prev/next/pause controls. (Optional hardening: layer a min-dwell guard on top so very short narrations don't outrun the reader.)
- [ ] Wire per-slide narration through `/api/voice/tts/stream/prepare` + a plain `<audio>` element (one call per slide; the chat's sentence-by-sentence `VoiceAgent.streamSpeakBegin/Feed/End` is not used here).
- [ ] Pre-warm `/prepare` for the next slide while the current one is playing.
- [ ] Skip TTS gracefully for slides with empty `narration_text`.
- [ ] Disable fuzzy slug fallback for admin GETs.
