"""pylego.action_queue — approval-queue safety helpers, ported from
@altay/admin-action-queue (the invariants, in dependency-free form).

The monolith already parks destructive admin actions in `admin_pending_actions`
with a `status` and approves them through a route. This module does NOT replace
that flow; it provides two reusable invariants the flow can adopt to harden it:

  * `validate_transition(current, target)` — enforce the legal status machine
    (pending → approved | rejected | expired; terminal states are final), so a
    double-click "Approve" can't re-execute an already-approved (or rejected)
    action.
  * `idempotency_key(...)` — a stable hash for an action so repeated submissions
    of the same proposal collapse to one queue entry.

Pure functions; no DB, no globals. Safe to unit-test and to wire incrementally.
"""

from __future__ import annotations

import hashlib
import json
from typing import Tuple

# Legal status machine for a parked action.
_TERMINAL = {"approved", "rejected", "expired"}
_ALLOWED = {
    "pending": {"approved", "rejected", "expired"},
}


def validate_transition(current: str, target: str) -> Tuple[bool, str]:
    """Return (ok, reason). Only `pending` may move, and only to a terminal
    state. Any transition out of a terminal state is rejected — this is what
    makes approve/reject idempotent against double-submits and races."""
    cur = (current or "").strip().lower()
    tgt = (target or "").strip().lower()
    if cur in _TERMINAL:
        return False, f"action already {cur}; no further transition allowed"
    allowed = _ALLOWED.get(cur)
    if allowed is None:
        return False, f"unknown current status {cur!r}"
    if tgt not in allowed:
        return False, f"illegal transition {cur} → {tgt}"
    return True, ""


def idempotency_key(session_id: str, tool_name: str, args) -> str:
    """Stable sha256 over (session, tool, normalized-args) so the same proposal
    submitted twice maps to one key. Args are JSON-normalized (sorted keys) when
    possible, else stringified."""
    try:
        norm = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        norm = str(args)
    raw = f"{session_id}\x1f{tool_name}\x1f{norm}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()
