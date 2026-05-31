"""Unit tests for the voice bridge — frame codec + provider interface.

These run WITHOUT `websockets` and without any API key: they exercise the pure
Twilio frame helpers and the EchoProvider round-trip (which is what proves the
relay contract). The live OpenAI path and the actual websocket server are
integration concerns verified with a real call (operator runbook).

Run:  python -m pytest voice_bridge/tests/test_bridge.py
"""

import asyncio
import base64
import json
import os
import sys

# Make `import voice_bridge` work when pytest is launched from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from voice_bridge import twilio_frames as tf            # noqa: E402
from voice_bridge.providers import get_provider, available  # noqa: E402
from voice_bridge.providers.echo import EchoProvider     # noqa: E402


# ---- frame codec ------------------------------------------------------------

def test_parse_frame_bad_input_is_empty():
    assert tf.parse_frame("not json") == {}
    assert tf.parse_frame("[1,2,3]") == {}     # not an object
    assert tf.parse_frame("") == {}


def test_stream_sid_from_start_and_toplevel():
    start = {"event": "start", "start": {"streamSid": "MZ123", "callSid": "CA1"}}
    assert tf.stream_sid(start) == "MZ123"
    assert tf.frame_event(start) == "start"
    assert tf.stream_sid({"streamSid": "MZ9"}) == "MZ9"


def test_decode_media_roundtrip():
    audio = b"\x7f\x7e\x7d\x7c"
    frame = {"event": "media", "media": {"payload": base64.b64encode(audio).decode()}}
    assert tf.decode_media(frame) == audio
    assert tf.decode_media({"event": "media"}) == b""   # missing payload → b""


def test_media_out_shape():
    out = json.loads(tf.media_out("MZ1", b"\x01\x02"))
    assert out["event"] == "media" and out["streamSid"] == "MZ1"
    assert base64.b64decode(out["media"]["payload"]) == b"\x01\x02"


def test_clear_and_mark_frames():
    assert json.loads(tf.clear_out("MZ1"))["event"] == "clear"
    m = json.loads(tf.mark_out("MZ1", "greeting"))
    assert m["event"] == "mark" and m["mark"]["name"] == "greeting"


# ---- provider registry ------------------------------------------------------

def test_registry_has_echo_and_openai_and_falls_back():
    names = available()
    assert "echo" in names and "openai" in names
    # Unknown name → safe fallback to Echo (never crashes the bridge).
    assert isinstance(get_provider("nope-not-real"), EchoProvider)


# ---- echo provider round-trip (the relay contract) --------------------------

def test_echo_provider_roundtrip():
    async def run():
        p = EchoProvider()
        await p.open()
        await p.send_caller_audio(b"aaa")
        await p.send_caller_audio(b"bbb")
        await p.close()                       # sentinel ends audio_out()
        got = []
        async for chunk in p.audio_out():
            got.append(chunk)
        return got
    assert asyncio.run(run()) == [b"aaa", b"bbb"]


def test_openai_provider_without_key_ends_cleanly():
    # With no OPENAI_API_KEY, open() must NOT raise and audio_out() must end
    # immediately (so the bridge falls back to silence rather than crashing).
    from voice_bridge.providers.openai_realtime import OpenAIRealtimeProvider

    async def run():
        p = OpenAIRealtimeProvider(api_key="")
        await p.open()
        out = []
        async for chunk in p.audio_out():
            out.append(chunk)
        return out
    assert asyncio.run(run()) == []
