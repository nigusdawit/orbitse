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

    __slots__ = ("rounds", "tool_calls", "tokens_in", "tokens_out", "cost_usd",
                 "model", "provider", "errored", "error_text", "final_text")

    def __init__(self) -> None:
        self.rounds = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.model = ""
        self.provider = ""
        self.errored = False
        self.error_text = ""
        self.final_text = ""

    def observe(self, evt: Dict[str, Any]) -> None:
        t = evt.get("type")
        if t == "tool_start":
            self.tool_calls += 1
        elif t == "usage":
            # The admin loop yields {"type":"usage","usage":{prompt_tokens,
            # completion_tokens, provider, model, cost_usd, ...}}. Tolerate a
            # flat shape too (other callers). Reading the nested dict is the fix
            # for tokens/cost always being 0.
            u = evt.get("usage") if isinstance(evt.get("usage"), dict) else evt
            self.rounds += 1
            self.tokens_in += int(u.get("prompt_tokens") or 0)
            self.tokens_out += int(u.get("completion_tokens") or 0)
            if u.get("cost_usd") is not None:
                try:
                    self.cost_usd += float(u.get("cost_usd") or 0)
                except (TypeError, ValueError):
                    pass
            if u.get("model"):
                self.model = str(u.get("model"))
            if u.get("provider"):
                self.provider = str(u.get("provider"))
        elif t == "error":
            self.errored = True
            self.error_text = str(evt.get("content") or "")[:500]
        elif t == "done":
            self.final_text = str(evt.get("content") or "")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rounds": self.rounds,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "errored": self.errored,
            "final_chars": len(self.final_text),
        }


def observe_admin_turn(meta: Dict[str, Any],
                       events: Iterable[Dict[str, Any]],
                       *,
                       persist_fn=None,
                       redact_enabled=None) -> Iterator[Dict[str, Any]]:
    """Wrap the admin chat event generator with observability.

    `meta` is light context for the trace (session_id, persona, user_message…).
    `events` is the generator returned by _admin_chat_stream_loop. Yields the
    exact same events, unchanged. Records timing + a tally to local logs, to
    Langfuse (if configured), and to an injected `persist_fn(record)` DB sink
    (if provided). `redact_enabled` overrides the config flag for redacting the
    record's text fields; None → use the config value.

    persist_fn / redaction failures are swallowed — they can never break the
    stream. The wrapped generator's own errors are always re-raised.
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
        _emit(meta, tally, started, status, persist_fn, redact_enabled)
        raise
    except BaseException as e:  # the loop's own failure — record, then re-raise.
        status = "exception"
        tally.errored = True
        tally.error_text = f"{type(e).__name__}: {e}"[:500]
        _emit(meta, tally, started, status, persist_fn, redact_enabled)
        raise
    else:
        if tally.errored:
            status = "error_event"
        _emit(meta, tally, started, status, persist_fn, redact_enabled)


def _emit(meta: Dict[str, Any], tally: _TurnTally, started: float, status: str,
          persist_fn=None, redact_enabled=None) -> None:
    """Write the trace to the configured backend(s) + the injected DB sink.
    Never raises (all sinks are guarded)."""
    try:
        cfg = config.get_config()
        do_redact = cfg.redact_enabled if redact_enabled is None else bool(redact_enabled)
        duration_ms = int((time.time() - started) * 1000)

        def _r(text):
            """Redact a text field when redaction is on. Never raises."""
            if not do_redact or not text:
                return text
            try:
                from . import redact
                return redact.redact_text(text)
            except Exception:
                return text

        # Full per-turn record. Text fields (error/question/answer) are redacted
        # so neither the log NOR the persisted activity row can leak a secret.
        record = {
            "event": "admin_chat_turn",
            "status": status,
            "duration_ms": duration_ms,
            "session_id": meta.get("session_id"),
            "persona": meta.get("persona"),
            "model": tally.model or meta.get("model") or "",
            "provider": tally.provider or meta.get("provider") or "",
            "rounds": tally.rounds,
            "tool_calls": tally.tool_calls,
            "tokens_in": tally.tokens_in,
            "tokens_out": tally.tokens_out,
            "cost_usd": round(tally.cost_usd, 6),
            "error_text": _r(tally.error_text) if (tally.errored and tally.error_text) else "",
            "user_message": _r(str(meta.get("user_message") or "")),
            "final_answer": _r(tally.final_text),
        }

        # Local structured log (a compact subset — no full content, to keep logs
        # light; the full content goes to the DB sink instead).
        if cfg.obs_local_logging:
            _log.info("admin_chat_turn %s", json.dumps(
                {k: record[k] for k in (
                    "status", "duration_ms", "session_id", "model", "provider",
                    "rounds", "tool_calls", "tokens_in", "tokens_out", "cost_usd",
                    "error_text")},
                default=str))

        # Injected DB sink (e.g. write a row to ai_activity_log). Guarded.
        if persist_fn is not None:
            try:
                persist_fn(record)
            except Exception:
                _log.debug("obs persist_fn failed (ignored)", exc_info=True)

        lf = _get_langfuse()
        if lf is not None:
            try:
                lf.trace(name="admin_chat_turn",
                         session_id=meta.get("session_id"),
                         metadata=record)
            except Exception:
                _log.debug("langfuse emit failed (ignored)", exc_info=True)
    except Exception:
        _log.debug("obs emit error (ignored)", exc_info=True)
