"""pylego — small, generic, configurable building blocks ported from the
TypeScript Lego library (~/lego) into Python for the Flask monolith.

Design rules (from the Lego philosophy, see PLAN_ADMIN_AI.md):
  * Single responsibility per module.
  * Every module is OFF-safe: when its `enabled` flag is false (or its optional
    dependency / config is absent) it degrades to a no-op or to current
    behavior — it NEVER changes or blocks the host's behavior.
  * Fail OPEN: an exception inside a pylego helper must never propagate into
    (and break) the caller's hot path (e.g. an admin chat turn). The one
    exception is the host's OWN errors, which we always let through unchanged.
  * Typed config with sane defaults; zero implicit globals; heavy comments.

These modules ENHANCE the Admin AI (observability, reliability, context,
safety) strictly additively. With pylego disabled the admin agent behaves
exactly as it did before pylego existed.
"""

__all__ = ["config", "obs", "evals"]
