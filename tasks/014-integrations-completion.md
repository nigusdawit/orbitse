# Task 014 — M14: integrations completion (voice admin, reviews agg, MCP OAuth, deck import, messaging/SMS)

## Goal
Finish the half-built integration surfaces so they're fully usable from admin.

## Acceptance criteria
- [x] Voice admin: `GET/PUT /admin/api/voice/settings`, voice-intros CRUD +
      `/generate` (pre-render intro audio), `/admin/api/voice/sample` preview,
      ElevenLabs dynamic voice list, legacy `POST /api/voice/tts` pre-gen,
      voice usage stats.
- [x] Reviews aggregation: real Google Places / Yelp Fusion / TripAdvisor fetch
      in `refresh_destination` + nightly snapshot sweep (in the collector tick);
      AI-drafted review-ask (gpt-4o-mini), sent via messaging.
- [x] MCP OAuth: `/admin/api/mcp/servers/<id>/oauth/start`, `/admin/oauth/mcp/
      callback`, `/oauth/disconnect`; connector blueprints list.
- [x] Presentations import: `POST /admin/api/presentations/import` (PPTX text +
      speaker-notes via python-pptx; per-slide JPGs best-effort via LibreOffice +
      pdftoppm; rejects unsupported types) + `/generate-narration` (AI).
- [x] Messaging: campaign `send_at` scheduling (tick from M10), SMS STOP/START
      opt-out + `POST /webhooks/twilio/inbound-sms` routed to the AI agent.

## Test requirements
- Gate (no live keys): voice settings/intros CRUD; reviews refresh records
  "key not configured" cleanly AND (mock) parses a sample payload; MCP oauth
  state transitions; import rejects unsupported types; SMS STOP flips opt-out.
- Live provider calls verified in M21.

## Dependencies: 010   ## Status: done   ## Branch: task/014-integrations-completion

## Notes
Merged to main (--no-ff). Gate: 277/277 incl. review parsers (legacy + new
Google shapes, Yelp, TripAdvisor), no-key refresh records a clean error, pptx
import (in-memory deck → title + speaker-notes→narration), unsupported-type
reject, legacy /api/voice/tts wired. Unit: `test_integrations.py` pins parsers,
MCP connector catalog, SMS keyword sets, and import slug derivation. Drift: most
of M14 (voice admin, reviews aggregation, MCP OAuth, messaging inbound) was
already built as **uncommitted** working-tree edits on this branch from a prior
session — committed here alongside the genuinely-new presentations import +
generate-narration + legacy TTS. Image rendering needs LibreOffice+pdftoppm at
runtime (absent in sandbox) → degrades to text+narration; live provider calls
(Google/Yelp/TA, ElevenLabs, Twilio) verified in M21.
