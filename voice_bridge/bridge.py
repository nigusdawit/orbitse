"""voice_bridge.bridge — the websocket server Twilio Media Streams connects to.

Run it:  VOICE_PROVIDER=echo python -m voice_bridge.bridge
Then expose it publicly (Replit/Render/ngrok) over wss:// and set the app's
AI Control → Live Call → voice_wss_url to that URL. Twilio dials it via the
TwiML <Connect><Stream url="wss://…"/></Connect> the app already emits.

Per call: accept the socket → wait for Twilio's 'start' frame → open the chosen
VoiceProvider → run two concurrent pumps:
  * inbound:  Twilio 'media' frames → provider.send_caller_audio()
  * outbound: provider.audio_out() → Twilio 'media' frames
Closes both when Twilio sends 'stop' or the socket drops. Everything is
fail-safe — one bad frame or an upstream hiccup ends the call cleanly.

Only third-party dependency: `websockets` (see requirements.txt).
"""

from __future__ import annotations

import asyncio
import os

from . import twilio_frames as tf
from .providers import get_provider, available


async def _pump_provider_to_twilio(ws, provider, get_sid) -> None:
    """provider.audio_out() → Twilio 'media' frames."""
    try:
        async for chunk in provider.audio_out():
            sid = get_sid()
            if sid and chunk:
                await ws.send(tf.media_out(sid, chunk))
    except Exception:
        pass


async def handle_call(ws) -> None:
    """Handle one Twilio Media Streams websocket connection."""
    provider_name = os.environ.get("VOICE_PROVIDER", "echo")
    provider = get_provider(provider_name)
    state = {"sid": ""}
    out_task = None
    opened = False
    try:
        async for message in ws:
            frame = tf.parse_frame(message)
            event = tf.frame_event(frame)
            if event == "start":
                state["sid"] = tf.stream_sid(frame)
                await provider.open()
                opened = True
                out_task = asyncio.create_task(
                    _pump_provider_to_twilio(ws, provider, lambda: state["sid"]))
            elif event == "media":
                if opened:
                    await provider.send_caller_audio(tf.decode_media(frame))
            elif event == "stop":
                break
            # 'connected' / 'mark' frames need no action here.
    except Exception:
        pass
    finally:
        try:
            await provider.close()
        except Exception:
            pass
        if out_task is not None:
            try:
                await asyncio.wait_for(out_task, timeout=2.0)
            except Exception:
                out_task.cancel()


async def _ws_handler(ws, *args):
    # websockets passes (ws) on v11+ and (ws, path) on older versions; accept both.
    await handle_call(ws)


async def main() -> None:
    import websockets  # imported here so tests can import frame/provider code dep-free
    host = os.environ.get("VOICE_BRIDGE_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT") or os.environ.get("VOICE_BRIDGE_PORT") or 8080)
    print(f"[voice_bridge] provider={os.environ.get('VOICE_PROVIDER', 'echo')} "
          f"(available: {', '.join(available())}) listening on ws://{host}:{port}")
    async with websockets.serve(_ws_handler, host, port, max_size=None):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
