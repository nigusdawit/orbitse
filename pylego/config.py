"""pylego.config — one typed, env-driven settings object for every pylego knob.

Ported from @altay/typed-config: a single place that reads environment
variables once, coerces them to the right type, and exposes them as a frozen
dataclass with safe defaults. No third-party dependency (stdlib only) so it can
never fail to import on a fresh host.

Every feature defaults to the *least disruptive* setting:
  * observability defaults ON but to local structured logging only (no external
    calls, no behavior change) — it upgrades to Langfuse automatically when keys
    are present.
  * The heavier behavior-affecting modules (reliability/context/safety, added in
    later tasks) default OFF here and are turned on deliberately.

Read once at import via `get_config()`; call `reload_config()` in tests after
monkeypatching os.environ.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PylegoConfig:
    # ---- Observability (task 026) -------------------------------------------
    # Master switch for the obs wrapper. When False, observe_admin_turn is a
    # pure pass-through (zero overhead, no logging).
    obs_enabled: bool
    # Emit a structured local log line per admin turn (cheap, no external dep).
    obs_local_logging: bool
    # Langfuse lights up automatically ONLY when enabled AND both keys exist.
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str

    # ---- Reliability (task 027) — ALL default to no-op / current behavior ----
    # Each of these is inert at its default value: timeout 0 = "use SDK default"
    # (no change), retries 0 = "no extra attempts" (current behavior), fallback
    # off, rate limit off. Operators opt in via env for production.
    llm_timeout_seconds: float        # per-call timeout; <=0 → unchanged (SDK default)
    llm_max_retries: int              # extra attempts on transient stream-open errors; 0 → none
    provider_fallback_enabled: bool   # try the other provider if the primary fails to open
    admin_chat_fallback_model: str    # model name to use for the fallback provider ("" → no fallback)
    admin_rate_limit_enabled: bool
    admin_rate_limit_max: int         # requests per window
    admin_rate_limit_window_seconds: int
    admin_rate_limit_store: str       # "postgres" (cluster-wide) | "memory" (per-process)

    # ---- Smarter context (task 028 — defaults off / current behavior) -------
    history_token_budget: int         # 0 == disabled (keep fixed-turn behavior)
    respcache_enabled: bool
    respcache_threshold: float

    # ---- Safety (task 029) --------------------------------------------------
    # sqlguard/structured default OFF (they can affect behavior — they're a
    # stricter layer on top of the monolith's existing guards). redact defaults
    # ON because it only sanitizes observability output (logs/traces) — it can
    # never change app behavior, responses, or stored data, so it's safe-by-default.
    sqlguard_enabled: bool
    structured_enabled: bool
    redact_enabled: bool

    @property
    def langfuse_active(self) -> bool:
        """True only when obs is on AND real Langfuse keys are present."""
        return bool(self.obs_enabled and self.langfuse_public_key
                    and self.langfuse_secret_key)


def _build() -> PylegoConfig:
    return PylegoConfig(
        # Observability: ON by default but local-logging only (non-disruptive).
        obs_enabled=_env_bool("PYLEGO_OBS_ENABLED", True),
        obs_local_logging=_env_bool("PYLEGO_OBS_LOCAL_LOGGING", True),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip(),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", "").strip(),
        langfuse_base_url=os.environ.get(
            "LANGFUSE_BASE_URL", "https://cloud.langfuse.com").strip(),
        # Reliability — wired in 027; defaults are INERT (= current behavior).
        llm_timeout_seconds=_env_float("ADMIN_CHAT_LLM_TIMEOUT", 0.0),     # 0 → SDK default
        llm_max_retries=_env_int("ADMIN_CHAT_LLM_MAX_RETRIES", 0),         # 0 → no extra attempts
        provider_fallback_enabled=_env_bool("ADMIN_CHAT_PROVIDER_FALLBACK", False),
        admin_chat_fallback_model=os.environ.get("ADMIN_CHAT_FALLBACK_MODEL", "").strip(),
        admin_rate_limit_enabled=_env_bool("ADMIN_CHAT_RATE_LIMIT_ENABLED", False),
        admin_rate_limit_max=_env_int("ADMIN_CHAT_RATE_LIMIT_MAX", 60),
        admin_rate_limit_window_seconds=_env_int("ADMIN_CHAT_RATE_LIMIT_WINDOW", 60),
        admin_rate_limit_store=os.environ.get("ADMIN_CHAT_RATE_LIMIT_STORE", "postgres").strip().lower(),
        # Smarter context — wired in 028.
        history_token_budget=_env_int("ADMIN_CHAT_HISTORY_TOKEN_BUDGET", 0),
        respcache_enabled=_env_bool("ADMIN_RESPCACHE_ENABLED", False),
        respcache_threshold=_env_float("ADMIN_RESPCACHE_THRESHOLD", 0.93),
        # Safety — wired in 029.
        sqlguard_enabled=_env_bool("ADMIN_SQLGUARD_ENABLED", False),
        structured_enabled=_env_bool("ADMIN_STRUCTURED_ARGS_ENABLED", False),
        redact_enabled=_env_bool("ADMIN_REDACT_ENABLED", True),  # log-only → safe default-on
    )


_CONFIG: PylegoConfig | None = None
_LOCK = threading.Lock()


def get_config() -> PylegoConfig:
    """Return the process-wide config, building it once on first use."""
    global _CONFIG
    if _CONFIG is None:
        with _LOCK:
            if _CONFIG is None:
                _CONFIG = _build()
    return _CONFIG


def reload_config() -> PylegoConfig:
    """Rebuild from the current environment (test helper)."""
    global _CONFIG
    with _LOCK:
        _CONFIG = _build()
    return _CONFIG
