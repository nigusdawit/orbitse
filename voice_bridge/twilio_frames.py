"""voice_bridge.twilio_frames — Twilio Media Streams wire-format helpers.

Twilio's <Connect><Stream> opens a WebSocket to our bridge and exchanges small
JSON *text* frames. Inbound (Twilio → us):
  {"event":"connected", ...}
  {"event":"start","start":{"streamSid":"MZ..","callSid":"CA..",
      "mediaFormat":{"encoding":"audio/x-mulaw","sampleRate":8000,"channels":1}}}
  {"event":"media","media":{"track":"inbound","payload":"<base64 G711 μ-law>"}}
  {"event":"mark","mark":{"name":".."}}
  {"event":"stop", ...}
Outbound (us → Twilio):
  {"event":"media","streamSid":sid,"media":{"payload":"<base64 μ-law>"}}
  {"event":"mark","streamSid":sid,"mark":{"name":".."}}
  {"event":"clear","streamSid":sid}        # barge-in: drop buffered audio

The audio is 8 kHz mono G.711 μ-law — the SAME format OpenAI's Realtime API can
speak natively (`g711_ulaw`), so this bridge needs no resampling. These helpers
are pure (no I/O, no deps) so they're trivially unit-testable.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict


def parse_frame(text: str) -> Dict[str, Any]:
    """Parse one inbound Twilio frame. Returns {} on anything unparseable
    (never raises — a malformed frame must not kill the call loop)."""
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def frame_event(frame: Dict[str, Any]) -> str:
    return str((frame or {}).get("event") or "")


def stream_sid(frame: Dict[str, Any]) -> str:
    """streamSid from a 'start' frame (nested) or any frame (top-level)."""
    f = frame or {}
    start = f.get("start") or {}
    return str(start.get("streamSid") or f.get("streamSid") or "")


def decode_media(frame: Dict[str, Any]) -> bytes:
    """Raw μ-law bytes from a 'media' frame ('' → b'')."""
    payload = ((frame or {}).get("media") or {}).get("payload") or ""
    if not payload:
        return b""
    try:
        return base64.b64decode(payload)
    except Exception:
        return b""


def media_out(sid: str, mulaw: bytes) -> str:
    """Build an outbound 'media' frame carrying μ-law audio for Twilio to play."""
    return json.dumps({
        "event": "media",
        "streamSid": sid,
        "media": {"payload": base64.b64encode(mulaw or b"").decode("ascii")},
    })


def mark_out(sid: str, name: str) -> str:
    """A 'mark' lets us know (via the echoed mark frame) when Twilio finished
    playing everything queued up to this point — useful for turn-taking."""
    return json.dumps({"event": "mark", "streamSid": sid, "mark": {"name": name}})


def clear_out(sid: str) -> str:
    """Tell Twilio to drop any buffered outbound audio (barge-in / interrupt)."""
    return json.dumps({"event": "clear", "streamSid": sid})
