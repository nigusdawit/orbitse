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

    # ---- Reliability (task 027 — defined now, defaults are no-ops) ----------
    llm_timeout_seconds: float        # per-call timeout applied by llm_router
    llm_max_retries: int              # bounded retry on transient errors
    provider_fallback_enabled: bool   # OpenAI<->Claude fallback chain
    admin_rate_limit_enabled: bool
    admin_rate_limit_max: int         # requests per window
    admin_rate_limit_window_seconds: int

    # ---- Smarter context (task 028 — defaults off / current behavior) -------
    history_token_budget: int         # 0 == disabled (keep fixed-turn behavior)
    respcache_enabled: bool
    respcache_threshold: float

    # ---- Safety (task 029 — defaults off / current behavior) ----------------
    sqlguard_enabled: bool
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
        # Reliability — wired in 027; safe defaults mean "current behavior".
        llm_timeout_seconds=_env_float("ADMIN_CHAT_LLM_TIMEOUT", 60.0),
        llm_max_retries=_env_int("ADMIN_CHAT_LLM_MAX_RETRIES", 2),
        provider_fallback_enabled=_env_bool("ADMIN_CHAT_PROVIDER_FALLBACK", False),
        admin_rate_limit_enabled=_env_bool("ADMIN_CHAT_RATE_LIMIT_ENABLED", False),
        admin_rate_limit_max=_env_int("ADMIN_CHAT_RATE_LIMIT_MAX", 60),
        admin_rate_limit_window_seconds=_env_int("ADMIN_CHAT_RATE_LIMIT_WINDOW", 60),
        # Smarter context — wired in 028.
        history_token_budget=_env_int("ADMIN_CHAT_HISTORY_TOKEN_BUDGET", 0),
        respcache_enabled=_env_bool("ADMIN_RESPCACHE_ENABLED", False),
        respcache_threshold=_env_float("ADMIN_RESPCACHE_THRESHOLD", 0.93),
        # Safety — wired in 029.
        sqlguard_enabled=_env_bool("ADMIN_SQLGUARD_ENABLED", False),
        redact_enabled=_env_bool("ADMIN_REDACT_ENABLED", False),
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
