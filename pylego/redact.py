"""pylego.redact — PII/secret redaction, ported from @altay/pii-redact.

A small, dependency-free redactor for strings that are about to leave the
trust boundary in a NON-response channel — primarily observability output
(logs / traces), where an exception message could otherwise carry an API key,
an email, or a phone number.

Scope note: the monolith already redacts tool-call arguments and DB rows
(`_redact_sensitive_args`, `_redact_recursive`) on the chat path. This module
does NOT duplicate or replace that — it's aimed at the observability strings
pylego.obs emits (error_text), and is available as a generic helper.

NON-DISRUPTION: redaction only ever rewrites a *string we are about to log*; it
never changes app behavior, responses, or stored data. `redact_text` is
total (never raises) and returns the input unchanged on any error.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_MASK = "[REDACTED]"

# Ordered, conservative patterns. Each captures a value we never want in logs.
_PATTERNS: List[re.Pattern] = [
    # Provider-style secret tokens: sk-..., pk_..., rk-..., Bearer xxxxx, ghp_...
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|xoxb|xoxp)[-_][A-Za-z0-9]{6,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"),
    # key=value / key: value where key looks secret.
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b\s*[:=]\s*\S+"),
    # Emails.
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # Long digit runs (phone / card / account / id) — 9+ digits, allowing separators.
    re.compile(r"\b\d[\d ()+\-]{7,}\d\b"),
]


def redact_text(text: Any) -> Any:
    """Return `text` with PII/secret-looking substrings masked. Non-strings are
    returned unchanged. Never raises."""
    if not isinstance(text, str) or not text:
        return text
    try:
        out = text
        for pat in _PATTERNS:
            out = pat.sub(_MASK, out)
        return out
    except Exception:
        return text


def redact_mapping(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """Return a shallow copy of `d` with `redact_text` applied to the given
    string keys. Useful for sanitizing a small log/trace record. Never raises."""
    try:
        if not isinstance(d, dict):
            return d
        out = dict(d)
        for k in keys:
            if k in out and isinstance(out[k], str):
                out[k] = redact_text(out[k])
        return out
    except Exception:
        return d
