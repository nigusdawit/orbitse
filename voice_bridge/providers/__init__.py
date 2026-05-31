"""voice_bridge.providers — registry + factory for swappable voice backends.

Pick the backend with the VOICE_PROVIDER env var (default 'echo'). To add a new
one: implement VoiceProvider in a new module and register it in _PROVIDERS.
"""

from __future__ import annotations

from typing import Dict, Type

from .base import VoiceProvider
from .echo import EchoProvider
from .openai_realtime import OpenAIRealtimeProvider

# name → class. Add Deepgram / Gemini Live / self-hosted pipeline here once you
# implement the VoiceProvider interface for them (see README → Adding a provider).
_PROVIDERS: Dict[str, Type[VoiceProvider]] = {
    "echo": EchoProvider,
    "openai": OpenAIRealtimeProvider,
    # "deepgram": DeepgramProvider,
    # "gemini":   GeminiLiveProvider,
}


def available() -> list:
    return sorted(_PROVIDERS.keys())


def get_provider(name: str, **opts) -> VoiceProvider:
    """Instantiate a provider by name. Unknown names fall back to 'echo' so the
    bridge always has a working (if non-AI) backend rather than crashing."""
    cls = _PROVIDERS.get((name or "echo").strip().lower(), EchoProvider)
    return cls(**opts)


__all__ = ["VoiceProvider", "get_provider", "available"]
