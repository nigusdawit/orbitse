# Task 014 — M14: integrations completion (voice admin, reviews agg, MCP OAuth, deck import, messaging/SMS)

## Goal
Finish the half-built integration surfaces so they're fully usable from admin.

## Acceptance criteria
- [ ] Voice admin: `GET/PUT /admin/api/voice/settings`, voice-intros CRUD +
      `/generate` (pre-render intro audio), `/admin/api/voice/sample` preview,
      ElevenLabs dynamic voice list, legacy `POST /api/voice/tts` pre-gen,
      voice usage stats.
- [ ] Reviews aggregation: real Google Places / Yelp Fusion / TripAdvisor fetch
      in `refresh_destination` + nightly snapshot tick; AI-drafted review-ask
      (gpt-4o-mini) wrapped in the admin template, sent via messaging.
- [ ] MCP OAuth: `/admin/api/mcp/servers/<id>/oauth/start`, `/admin/oauth/mcp/
      callback`, `/oauth/disconnect`; connector blueprints list.
- [ ] Presentations import: `POST /admin/api/presentations/import` (Office/PPTX →
      PDF via LibreOffice → per-slide JPGs; pptx notes → narration) +
      `/generate-narration` (AI).
- [ ] Messaging: campaign `send_at` scheduling (tick from M10), SMS STOP-keyword
      opt-out + `POST /webhooks/twilio/inbound-sms` routed to the AI agent.

## Test requirements
- Gate (no live keys): voice settings/intros CRUD; reviews refresh records
  "key not configured" cleanly AND (mock) parses a sample payload; MCP oauth
  state transitions; import rejects unsupported types; SMS STOP flips opt-out.
- Live provider calls verified in M21.

## Dependencies: 010   ## Status: not_started   ## Branch: task/014-integrations-completion
