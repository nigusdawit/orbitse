"""voice_bridge.providers.openai_realtime — reference realtime provider.

Bridges the call to OpenAI's Realtime API. We use the API's native
`g711_ulaw` audio format on BOTH input and output, which is exactly Twilio's
8 kHz μ-law — so no resampling/transcoding is needed anywhere in the pipe.

Talks to OpenAI over a raw WebSocket (only dep: `websockets`) so we don't pull
in the full SDK. Needs OPENAI_API_KEY. This is ONE reference implementation —
see README "Adding a provider" to wire Deepgram / Gemini Live / a self-hosted
pipeline behind the same VoiceProvider interface.

All failures end audio_out() cleanly instead of raising into the bridge.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import AsyncIterator, Optional

from .base import VoiceProvider

_OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"


class OpenAIRealtimeProvider(VoiceProvider):
    name = "openai"

    def __init__(self, *, api_key: Optional[str] = None, model: Optional[str] = None,
                 voice: Optional[str] = None, instructions: Optional[str] = None,
                 **_opts) -> None:
        self._api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        self._model = (model or os.environ.get("VOICE_MODEL")
                       or "gpt-4o-realtime-preview").strip()
        self._voice = (voice or os.environ.get("VOICE_NAME") or "alloy").strip()
        self._instructions = (instructions
                              or os.environ.get("VOICE_INSTRUCTIONS")
                              or "You are a friendly, concise phone assistant for this business.")
        self._ws = None
        self._out: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._closed = False

    async def open(self) -> None:
        if not self._api_key:
            # No key → behave like a clean, immediate end (bridge falls silent;
            # the operator should set OPENAI_API_KEY). Never raise.
            await self._out.put(None)
            return
        import websockets  # imported lazily so the module loads without the dep
        url = f"{_OPENAI_REALTIME_URL}?model={self._model}"
        headers = [("Authorization", f"Bearer {self._api_key}"),
                   ("OpenAI-Beta", "realtime=v1")]
        try:
            self._ws = await websockets.connect(url, additional_headers=headers,
                                                max_size=None)
        except TypeError:
            # Older websockets used extra_headers= instead of additional_headers=.
            self._ws = await websockets.connect(url, extra_headers=headers,
                                                max_size=None)
        # Configure the session for Twilio-native μ-law in/out + server VAD so
        # the model decides when the caller stopped talking.
        await self._ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": self._voice,
                "instructions": self._instructions,
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "turn_detection": {"type": "server_vad"},
            },
        }))
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Pump OpenAI events; forward output audio deltas to the queue."""
        try:
            async for raw in self._ws:
                try:
                    evt = json.loads(raw)
                except Exception:
                    continue
                etype = evt.get("type") or ""
                if etype == "response.audio.delta" and evt.get("delta"):
                    try:
                        self._out.put_nowait(base64.b64decode(evt["delta"]))
                    except Exception:
                        pass
                # response.audio.done / response.done are informational here.
        except Exception:
            pass
        finally:
            await self._out.put(None)

    async def send_caller_audio(self, mulaw: bytes) -> None:
        if self._closed or self._ws is None or not mulaw:
            return
        try:
            await self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(mulaw).decode("ascii"),
            }))
        except Exception:
            pass

    async def audio_out(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._out.get()
            if chunk is None:
                return
            yield chunk

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._reader_task:
                self._reader_task.cancel()
        except Exception:
            pass
        try:
            if self._ws is not None:
                await self._ws.close()
        except Exception:
            pass
        await self._out.put(None)
