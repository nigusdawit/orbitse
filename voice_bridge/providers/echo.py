"""voice_bridge.providers.echo — a zero-dependency, zero-credential provider.

EchoProvider just plays the caller's own audio back to them. It exists so you
can verify the ENTIRE Twilio ↔ bridge round-trip (TwiML <Stream>, websocket,
frame codec, relay loop) end-to-end WITHOUT any AI provider or API key — call
your number, talk, and hear yourself. It's also what the unit tests exercise.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from .base import VoiceProvider


class EchoProvider(VoiceProvider):
    name = "echo"

    def __init__(self, **_opts) -> None:
        self._q: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._closed = False

    async def open(self) -> None:
        self._closed = False

    async def send_caller_audio(self, mulaw: bytes) -> None:
        # Echo: whatever comes in goes straight back out.
        if not self._closed and mulaw:
            await self._q.put(mulaw)

    async def audio_out(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._q.get()
            if chunk is None:        # close() sentinel
                return
            yield chunk

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._q.put(None)
