"""pylego.obs — observability for the Admin AI, ported from @altay/langfuse-client.

Goal: see what the admin agent is doing (latency, tool calls, token usage,
errors) WITHOUT changing or risking its behavior. The public entry point is
`observe_admin_turn(meta, events)` — a generator wrapper you put around the
admin chat loop's event generator. It forwards every event byte-for-byte and
records a trace on the side.

NON-DISRUPTION GUARANTEES (the whole point):
  * Pass-through: every event yielded by the wrapped generator is re-yielded
    unchanged, in order. The wrapper adds nothing to and removes nothing from
    the stream.
  * Fail-open: any error inside the observability code is swallowed (logged at
    debug). It can never break or stall a chat turn.
  * The wrapped generator's OWN exceptions are always re-raised (we never hide
    the chat's real errors) — we just close the trace first.
  * Disabled / unconfigured → the wrapper is a thin pass-through with no I/O.

Backends, chosen automatically:
  * Default: a structured local log line per turn (stdlib logging, no deps).
  * Langfuse: used additionally when `config.langfuse_active` (obs on + keys
    present) AND the `langfuse` Python SDK is importable. Lazy, guarded import.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, Iterator

from . import config

_log = logging.getLogger("pylego.obs")

# Cache the resolved Langfuse client across turns: None = not yet tried,
# False = tried and unavailable, object = ready. Keeps the hot path cheap.
_LANGFUSE: Any = None


def _get_langfuse():
    """Return a Langfuse client if obs is configured for it and the SDK is
    importable, else None. Never raises."""
    global _LANGFUSE
    cfg = config.get_config()
    if not cfg.langfuse_active:
        return None
    if _LANGFUSE is False:
        return None
    if _LANGFUSE is not None:
        return _LANGFUSE
    try:
        from langfuse import Langfuse  # type: ignore
        _LANGFUSE = Langfuse(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=cfg.langfuse_base_url,
        )
    except Exception as e:  # SDK missing or misconfigured → degrade silently.
        _log.debug("langfuse unavailable, using local logging only: %s", e)
        _LANGFUSE = False
        return None
    return _LANGFUSE


class _TurnTally:
    """Mutable counters accumulated as events stream by. Plain object so
    updating it is allocation-free and exception-free."""

    __slots__ = ("rounds", "tool_calls", "tokens_in", "tokens_out",
                 "errored", "error_text", "final_chars")

    def __init__(self) -> None:
        self.rounds = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.errored = False
        self.error_text = ""
        self.final_chars = 0

    def observe(self, evt: Dict[str, Any]) -> None:
        t = evt.get("type")
        if t == "tool_start":
            self.tool_calls += 1
        elif t == "usage":
            # The loop yields {"type":"usage","prompt_tokens":..,"completion_tokens":..}
            self.rounds += 1
            self.tokens_in += int(evt.get("prompt_tokens") or 0)
            self.tokens_out += int(evt.get("completion_tokens") or 0)
        elif t == "error":
            self.errored = True
            self.error_text = str(evt.get("content") or "")[:500]
        elif t == "done":
            self.final_chars = len(str(evt.get("content") or ""))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "errored": self.errored,
            "final_chars": self.final_chars,
        }


def observe_admin_turn(meta: Dict[str, Any],
                       events: Iterable[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """Wrap the admin chat event generator with observability.

    `meta` is light context for the trace (session_id, model, provider, etc.).
    `events` is the generator returned by _admin_chat_stream_loop. Yields the
    exact same events, unchanged. Records timing + a tally to local logs and
    (if configured) Langfuse.

    Usage at the call site:
        for evt in observe_admin_turn(meta, _admin_chat_stream_loop(...)):
            ...
    """
    cfg = config.get_config()

    # Disabled → pure pass-through, nothing else happens.
    if not cfg.obs_enabled:
        yield from events
        return

    started = time.time()
    tally = _TurnTally()
    status = "ok"

    try:
        for evt in events:
            # Observation must never break the stream. Tally first (guarded),
            # then yield the event untouched no matter what.
            try:
                if isinstance(evt, dict):
                    tally.observe(evt)
            except Exception:
                _log.debug("obs tally error (ignored)", exc_info=True)
            yield evt
    except GeneratorExit:
        # Consumer (HTTP client) disconnected mid-stream.
        status = "client_closed"
        _emit(meta, tally, started, status)
        raise
    except BaseException as e:  # the loop's own failure — record, then re-raise.
        status = "exception"
        tally.errored = True
        tally.error_text = f"{type(e).__name__}: {e}"[:500]
        _emit(meta, tally, started, status)
        raise
    else:
        if tally.errored:
            status = "error_event"
        _emit(meta, tally, started, status)


def _emit(meta: Dict[str, Any], tally: _TurnTally, started: float, status: str) -> None:
    """Write the trace to the configured backend(s). Never raises."""
    try:
        cfg = config.get_config()
        duration_ms = int((time.time() - started) * 1000)
        record = {
            "event": "admin_chat_turn",
            "status": status,
            "duration_ms": duration_ms,
            **{k: meta.get(k) for k in ("session_id", "model", "provider", "persona")},
            **tally.as_dict(),
        }
        if tally.errored and tally.error_text:
            record["error_text"] = tally.error_text

        if cfg.obs_local_logging:
            _log.info("admin_chat_turn %s", json.dumps(record, default=str))

        lf = _get_langfuse()
        if lf is not None:
            try:
                # Langfuse v3-style trace creation; guarded so any SDK version
                # mismatch just degrades to local logging.
                lf.trace(name="admin_chat_turn",
                         session_id=meta.get("session_id"),
                         metadata=record)
            except Exception:
                _log.debug("langfuse emit failed (ignored)", exc_info=True)
    except Exception:
        _log.debug("obs emit error (ignored)", exc_info=True)
