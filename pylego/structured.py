"""pylego.structured — safe tool-argument parsing + retry-with-feedback,
ported from @altay/structured-llm (the recovery loop, in dependency-free form).

Two helpers:
  * `parse_tool_args(raw)` — turn an LLM's tool-call argument blob into a dict,
    returning a clear error instead of silently collapsing to `{}` (which makes
    a tool run with wrong defaults and produces confusing results).
  * `run_with_repair(call_fn, parse_fn, max_retries)` — generic
    "call → parse → on failure feed the error back and retry" loop for
    structured outputs.

These are building blocks; wiring is opt-in (the monolith currently tolerates
malformed args by defaulting to `{}`). Total / never raises out of `parse_tool_args`.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple


def parse_tool_args(raw: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (args_dict, error). On success error is "". On failure args is
    None and error explains why — so the caller can hand the model a useful
    'your arguments were invalid because X, try again' message instead of
    silently running the tool with empty args."""
    if raw is None or raw == "":
        return {}, ""  # no args is legitimately {} for zero-arg tools
    if isinstance(raw, dict):
        return raw, ""
    if not isinstance(raw, str):
        return None, f"tool arguments must be a JSON object, got {type(raw).__name__}"
    try:
        obj = json.loads(raw)
    except Exception as e:
        return None, f"arguments were not valid JSON: {e}"
    if not isinstance(obj, dict):
        return None, "arguments must be a JSON object (got a non-object JSON value)"
    return obj, ""


def run_with_repair(call_fn: Callable[[Optional[str]], Any],
                    parse_fn: Callable[[Any], Tuple[Optional[Any], str]],
                    *, max_retries: int = 1) -> Tuple[Optional[Any], str]:
    """Call `call_fn(feedback)` → `parse_fn(result)`; on a parse error, retry
    up to `max_retries` times, passing the prior error back as `feedback` so the
    model can correct itself. Returns (parsed, error). `error` is "" on success.

    Generic + side-effect-free here (the caller supplies call_fn/parse_fn), so
    it's safe to unit-test and to wire only where desired."""
    feedback: Optional[str] = None
    last_err = ""
    for _ in range(max(1, 1 + max_retries)):
        try:
            raw = call_fn(feedback)
        except Exception as e:
            return None, f"call failed: {type(e).__name__}: {e}"
        parsed, err = parse_fn(raw)
        if not err:
            return parsed, ""
        last_err = err
        feedback = err
    return None, last_err
