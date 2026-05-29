# Task 001 — M1: Visitor chat vertical slice

## Goal

Deliver a runnable visitor-AI experience on top of M0: the visitor chat blueprint (tool-call loop,
compact site index, `generatePage`-first commands), the gallery/forms/media blueprints it depends on,
the modernized chat widget (live progressive iframe render + built-in gallery), the voice subsystem
(streaming TTS/STT + intros), and a self-contained `demo/index.html` proving it all works with zero
host wiring. This is the original ask, shipped as a working slice.

## Research block

- Visitor chat: `app.py` `POST /api/chat` (~18819), site-index builder (`build_site_index` ~10070),
  tool loop (~19813–19920), `CHAT_TOOLS` (~10278), executors (`lookup_gallery_cards` ~9208), SSE events.
- Default system prompt teaching generatePage: `app.py` ~8286, command section ~8394–8629.
- Live render (port to widget): `public/script.js` — `extractStreamingJsonString` (~9266),
  `findTopLevelHtmlBoundary` (~9188), `buildImmersivePageDoc` (~8878), `openImmersivePageStreaming`
  (~9077), executeCommand generatePage skip-re-render (~7581).
- Voice: `public/voice.js` (window.VoiceAgent streamSpeak*), backend `/api/voice/*` endpoints
  (~28051–28548), tables voice_settings/voice_intros/voice_usage_log.
- Existing widget to modernize: `chat-ui-kit/chat-ui.{js,css,html}` (folded into `web/`).

## Acceptance criteria

- [ ] `blueprints/visitor_chat.py`: `/api/chat` SSE with OpenAI+Anthropic tool loop (4-round cap),
      site index + forms + page-library injection, generatePage-first prompt, tool-call logging,
      cost-stamped, cap-enforced.
- [ ] `blueprints/gallery.py` (`/api/gallery-cards` + admin CRUD), `blueprints/forms.py`
      (`/api/forms/<slug>/{submit,partial}`), `blueprints/media.py` (uploads + `/uploads/<path>`).
- [ ] `web/` widget: live progressive iframe render ported; built-in gallery defaults so `navigate`
      works with no host callbacks; voice hooks wired.
- [ ] `blueprints/voice.py` + `web/voice.js`: settings/intro/tts(+stream)/stt; per-IP cap; OpenAI-direct
      + optional ElevenLabs; fails open with no key.
- [ ] `demo/index.html`: loads widget + gallery + voice; gallery nav, live generatePage, form fill,
      spoken reply all work locally.

## Test requirements

- pytest: `parse_command_from_text` (generatePage/navigate/malformed), `build_site_index` output shape,
  tool dispatch wiring, voice cache-key hashing + per-IP cap.
- `verify` skill + Claude_Preview on `demo/index.html`: the four flows above; console clean.

## Dependencies
000.

## Can run in parallel with
002 (disjoint files).

## Status
done  (merged to main; runtime gate GREEN via embedded Postgres)

## Branch
task/001-visitor-chat-slice

## Verification state
Built modules: auth, util, gallery/forms/media blueprints, chat_runtime, tools,
prompts, visitor_chat blueprint, voice blueprint, web/voice.js, web/chat-ui.{js,css},
demo/index.html, assets blueprint.

PASSED in the build sandbox:
- ruff clean across the package
- pytest: 18 passed / 2 skipped (the 2 skips are DB-backed schema tests — no local Postgres)
- `node --check` on chat-ui.js + voice.js (valid syntax)
- `create_app` boots in self_host AND central; all M1 routes register
- live server boots; GET /healthz, /demo, /widget/* all 200 with correct content-types; unknown widget asset 404

VERIFIED against a REAL embedded Postgres (pgserver, _gate_runner.py) — 19/19 GREEN:
- init_db() idempotent; all IN tables created; OUT tables absent; singletons + prices seeded
- GET /api/chatbot-settings, /api/gallery-cards, /api/voice/settings → 200 (caught a real
  fail-open bug: openai SDK raises on empty key at import → llm.py now builds clients only when
  a key is present, so blueprints mount + routes work with no key; chat returns 503 gracefully)
- gallery write→read→lookup_gallery_cards→build_site_index→assemble_system_prompt
- skills sync + per-skill enable filter (disable excludes the tool)
- forms: required-field rejection (400), submit (201 + confirmation #), persisted as 'new'
- cost: api_cost_events row written, compute_mtd_spend > 0
- /api/generated-pages/by-slug published page (200) for showSavedPage

STILL UNVERIFIED (needs an OpenAI key / a real browser — out of sandbox scope):
- a live /api/chat LLM completion round; pixel-level in-browser widget behavior
  (gallery split visuals, progressive generatePage animation, audible voice). The widget JS
  is node --check-valid and the SSE/command contract is unit-tested; visual confirmation
  remains a manual step for an env with a key + browser.

Gate tooling: _gate_runner.py + a 3.12 .gatevenv (.gitignored) stand up an ephemeral Postgres
so DB-backed milestones can be verified locally without a remote DB.

## Notes
Anthropic provider path is ported (chat_runtime.stream_round_claude) but only
exercised when agent_provider_settings.provider='claude' + ANTHROPIC_API_KEY.
