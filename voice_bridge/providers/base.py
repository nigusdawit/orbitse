"""voice_bridge.providers.base — the provider abstraction.

A VoiceProvider is the "brain" on the other side of the phone call. The bridge
is provider-AGNOSTIC: it speaks Twilio Media Streams on one side and this small
interface on the other, so you can swap OpenAI Realtime for Deepgram, Google
Gemini Live, a self-hosted voice-pipeline, etc. without touching the bridge.

Contract (all audio is 8 kHz mono G.711 μ-law — Twilio's native format):
  * open()                  — establish the upstream session (once per call).
  * send_caller_audio(b)    — feed one chunk of inbound caller audio.
  * audio_out()             — async iterator yielding chunks of audio to PLAY
                              back to the caller; ends when the call/session
                              closes.
  * close()                 — tear down the upstream session.

Implementations MUST be fail-safe: an upstream error should end audio_out()
cleanly rather than raise into the bridge's relay loop.
"""

from __future__ import annotations

import abc
from typing import AsyncIterator


class VoiceProvider(abc.ABC):
    #: Human-readable name; set by subclasses.
    name: str = "base"

    @abc.abstractmethod
    async def open(self) -> None:
        """Establish the upstream realtime session. Called once after the
        Twilio 'start' frame, before any audio flows."""

    @abc.abstractmethod
    async def send_caller_audio(self, mulaw: bytes) -> None:
        """Feed one chunk of inbound caller audio (8 kHz μ-law) upstream."""

    @abc.abstractmethod
    def audio_out(self) -> AsyncIterator[bytes]:
        """Async-iterate chunks of outbound audio (8 kHz μ-law) to play to the
        caller. The iterator completes when the session ends."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Tear down the upstream session (idempotent)."""
