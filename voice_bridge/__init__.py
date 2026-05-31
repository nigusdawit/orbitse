"""voice_bridge — standalone Twilio Media Streams ↔ realtime-voice bridge.

A separate, self-contained service (NOT imported by the Flask app) that gives
the AI concierge a real phone voice. Twilio's <Connect><Stream> connects a call
to this bridge's websocket; the bridge relays audio to a pluggable VoiceProvider
(OpenAI Realtime by default, an Echo backend for credential-free testing, and
clear slots for others). See README.md and bridge.py.
"""
