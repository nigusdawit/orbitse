"""pylego.history — token-aware conversation trimming, ported from
@altay/chat-history's trim primitive.

The Admin AI loads a fixed 60 prior turns. For a busy client with long turns
that can blow past the model's context window and cause a hard provider 400
mid-stream. This trims the assembled OpenAI-style `messages` array to a token
budget — dropping the OLDEST prior-turn messages first — while:

  * always keeping the leading system prompt (messages[0] if it's a system msg),
  * always keeping the current turn (everything from the last `user` message on,
    including any RAG/system block injected just before it),
  * never orphaning a `tool` message from its parent assistant (OpenAI/Anthropic
    reject a `tool` message with no preceding tool_call) — we drop leading
    `tool` messages along with whatever we trimmed.

NON-DISRUPTION: `budget <= 0` → returns the SAME list unchanged (the default).
Any internal error → returns the original messages (fail-open). Token counting
uses tiktoken when available, else a safe chars/4 heuristic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_ENCODER = None
_ENCODER_TRIED = False


def _encoder():
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken  # type: ignore
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENCODER = None
    return _ENCODER


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Heuristic fallback: ~4 chars per token, rounded up.
    return (len(text) + 3) // 4


def message_tokens(msg: Dict[str, Any]) -> int:
    """Approximate token cost of one message: content + serialized tool_calls +
    a small fixed per-message overhead (role + framing)."""
    if not isinstance(msg, dict):
        return 0
    total = 4  # per-message framing overhead
    content = msg.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        # multimodal parts (text / image_url); count text, ignore image bytes.
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                total += estimate_tokens(str(part.get("text", "")))
            else:
                total += 8  # rough placeholder for a non-text part reference
    tcs = msg.get("tool_calls")
    if tcs:
        import json
        try:
            total += estimate_tokens(json.dumps(tcs, default=str))
        except Exception:
            total += 50
    return total


def total_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(message_tokens(m) for m in messages)


def trim_to_budget(messages: List[Dict[str, Any]], budget: int,
                   model: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return a trimmed copy of `messages` whose estimated tokens fit `budget`.

    Drops the oldest prior-turn messages first; preserves the system prompt and
    the current turn; never leaves a dangling `tool` message. Returns the input
    unchanged when budget<=0 or it already fits, or on any error (fail-open)."""
    try:
        if not messages or budget is None or budget <= 0:
            return messages
        if total_tokens(messages) <= budget:
            return messages

        # Preserve the leading system prompt.
        head: List[Dict[str, Any]] = []
        body_start = 0
        if isinstance(messages[0], dict) and messages[0].get("role") == "system":
            head = [messages[0]]
            body_start = 1

        # Preserve the current turn: from the last `user` message to the end
        # (this includes a RAG/system block injected right before it, and is the
        # part we must never drop).
        last_user = None
        for i in range(len(messages) - 1, body_start - 1, -1):
            if isinstance(messages[i], dict) and messages[i].get("role") == "user":
                last_user = i
                break
        if last_user is None:
            # No user message found — nothing safe to trim.
            return messages
        tail = messages[last_user:]
        middle = messages[body_start:last_user]

        def fits(mid: List[Dict[str, Any]]) -> bool:
            return total_tokens(head + mid + tail) <= budget

        # Drop oldest middle messages until we fit; after each drop, also discard
        # any now-leading `tool` messages so we never orphan a tool result.
        while middle and not fits(middle):
            middle = middle[1:]
            while middle and isinstance(middle[0], dict) and middle[0].get("role") == "tool":
                middle = middle[1:]

        return head + middle + tail
    except Exception:
        return messages  # fail-open: never break the turn over a trim error
