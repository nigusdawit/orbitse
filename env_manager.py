"""Admin-facing manager for environment variables and local .env file.

Design
------
* We NEVER show full secret values to the admin. Sensitive values
  (anything with KEY / SECRET / PASSWORD / TOKEN / SID / DSN in the
  key, plus DATABASE_URL which embeds a password) are masked to
  ``••••XXXX`` (last 4 chars). Non-sensitive config (URLs, emails,
  phone numbers, plain flags) may be shown in full.

* We NEVER write secrets to the database. The admin form can only
  write to a local ``.env`` file (gitignored). At process startup we
  load that file into ``os.environ`` *without* overriding values that
  are already set — so platform-managed Replit Secrets always win
  over the local ``.env`` fallback. That means in production the
  in-app form is effectively a way to manage *missing* secrets in
  development without ever shadowing a real secret.

* We REJECT writes for any key not on a whitelist. The whitelist is
  curated below from ``.env.example`` so the admin can't poke
  arbitrary process-wide variables.

* Atomic .env writes (tempfile + os.replace) so a crash mid-write
  cannot corrupt the file.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Iterable

# Path to the local .env file. Lives in the project root, beside this
# module, and is git-ignored (see .gitignore).
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# ---------------------------------------------------------------------------
# Curated whitelist of env vars the app cares about.
#
# Sourced from .env.example. Each entry has:
#   key:         the env var name
#   level:       "required" | "recommended" | "optional"
#   category:    UI grouping label
#   description: one-line user-facing description
#   sensitive:   True → mask to last 4 chars; False → may show in full
#   restart:     True → changes require a workflow restart to take effect
#                (most secrets used at request time are False)
#   url:         optional link to where to obtain the key
# ---------------------------------------------------------------------------
KNOWN_VARS: list[dict] = [
    # ---- Required ----
    {"key": "DATABASE_URL", "level": "required", "category": "Database",
     "description": "Postgres connection string. Embeds a password — masked.",
     "sensitive": True, "restart": True},
    {"key": "ADMIN_PASSWORD", "level": "required", "category": "Admin access",
     "description": "Password to log in to this admin dashboard.",
     "sensitive": True, "restart": False},

    # ---- AI providers (at least one required) ----
    {"key": "OPENAI_API_KEY", "level": "recommended", "category": "AI providers",
     "description": "Powers the chatbot. At least one AI provider is required.",
     "sensitive": True, "restart": False, "url": "https://platform.openai.com/api-keys"},
    {"key": "ANTHROPIC_API_KEY", "level": "recommended", "category": "AI providers",
     "description": "Alternative AI provider (Claude). At least one is required.",
     "sensitive": True, "restart": False, "url": "https://console.anthropic.com/settings/keys"},

    # ---- Strongly recommended ----
    {"key": "FLASK_SECRET_KEY", "level": "recommended", "category": "Security",
     "description": "Signs Flask session cookies. Auto-generated if unset (sessions don't survive redeploy).",
     "sensitive": True, "restart": True},
    {"key": "PUBLIC_BASE_URL", "level": "recommended", "category": "Site",
     "description": "Public canonical URL (no trailing slash). Used in emails, webhooks, SEO.",
     "sensitive": False, "restart": False},
    {"key": "FORCE_SECURE_COOKIES", "level": "optional", "category": "Security",
     "description": "Set to '1' in production to force HTTPS-only cookies.",
     "sensitive": False, "restart": True},
    {"key": "ADMIN_EMAIL", "level": "recommended", "category": "Admin access",
     "description": "Where weekly digest and alert emails are sent.",
     "sensitive": False, "restart": False},
    {"key": "ADMIN_PHONE", "level": "optional", "category": "Admin access",
     "description": "Where SMS alerts are sent (E.164 format, e.g. +15551234567).",
     "sensitive": False, "restart": False},

    # ---- Email (Resend) ----
    {"key": "RESEND_API_KEY", "level": "recommended", "category": "Email (Resend)",
     "description": "Required for outbound email (digests, password resets, contact form).",
     "sensitive": True, "restart": False, "url": "https://resend.com/api-keys"},
    {"key": "RESEND_FROM_EMAIL", "level": "recommended", "category": "Email (Resend)",
     "description": "From-address for outbound email. Must be a verified Resend sender.",
     "sensitive": False, "restart": False},
    {"key": "RESEND_WEBHOOK_SECRET", "level": "optional", "category": "Email (Resend)",
     "description": "Verifies inbound delivery webhooks from Resend.",
     "sensitive": True, "restart": False},

    # ---- SMS (Twilio) ----
    {"key": "TWILIO_ACCOUNT_SID", "level": "optional", "category": "SMS (Twilio)",
     "description": "Twilio account SID. Required to send SMS notifications.",
     "sensitive": True, "restart": False, "url": "https://console.twilio.com/"},
    {"key": "TWILIO_AUTH_TOKEN", "level": "optional", "category": "SMS (Twilio)",
     "description": "Twilio auth token. Required to send SMS notifications.",
     "sensitive": True, "restart": False},
    {"key": "TWILIO_FROM_NUMBER", "level": "optional", "category": "SMS (Twilio)",
     "description": "Twilio phone number to send from (E.164 format).",
     "sensitive": False, "restart": False},

    # ---- Stripe (live) ----
    {"key": "STRIPE_SECRET_KEY", "level": "optional", "category": "Stripe (live)",
     "description": "Live mode secret key (sk_live_…). Powers the storefront.",
     "sensitive": True, "restart": False, "url": "https://dashboard.stripe.com/apikeys"},
    {"key": "STRIPE_PUBLISHABLE_KEY", "level": "optional", "category": "Stripe (live)",
     "description": "Live mode publishable key (pk_live_…). Used by the checkout form.",
     "sensitive": True, "restart": False},
    {"key": "STRIPE_WEBHOOK_SECRET", "level": "optional", "category": "Stripe (live)",
     "description": "Verifies live webhook signatures (whsec_…).",
     "sensitive": True, "restart": False},

    # ---- Stripe (test / sandbox) ----
    {"key": "STRIPE_TEST_SECRET_KEY", "level": "optional", "category": "Stripe (test)",
     "description": "Test mode secret key (sk_test_…). Safe sandbox for development.",
     "sensitive": True, "restart": False},
    {"key": "STRIPE_TEST_PUBLISHABLE_KEY", "level": "optional", "category": "Stripe (test)",
     "description": "Test mode publishable key (pk_test_…).",
     "sensitive": True, "restart": False},
    {"key": "STRIPE_TEST_WEBHOOK_SECRET", "level": "optional", "category": "Stripe (test)",
     "description": "Verifies test webhook signatures.",
     "sensitive": True, "restart": False},

    # ---- Voice / Search / Reviews ----
    {"key": "ELEVENLABS_API_KEY", "level": "optional", "category": "Voice (ElevenLabs)",
     "description": "Enables AI voice playback in the chatbot.",
     "sensitive": True, "restart": False, "url": "https://elevenlabs.io/app/settings/api-keys"},
    {"key": "BRAVE_SEARCH_API_KEY", "level": "optional", "category": "Web search",
     "description": "Gives the chatbot a web-search tool it can invoke.",
     "sensitive": True, "restart": False, "url": "https://brave.com/search/api/"},
    {"key": "GOOGLE_PLACES_API_KEY", "level": "optional", "category": "Reviews",
     "description": "Pulls Google Maps reviews for the chatbot to reference.",
     "sensitive": True, "restart": False},
    {"key": "YELP_API_KEY", "level": "optional", "category": "Reviews",
     "description": "Pulls Yelp reviews for the chatbot to reference.",
     "sensitive": True, "restart": False},
    {"key": "TRIPADVISOR_API_KEY", "level": "optional", "category": "Reviews",
     "description": "Pulls TripAdvisor reviews for the chatbot to reference.",
     "sensitive": True, "restart": False},

    # ---- Observability ----
    {"key": "SENTRY_DSN", "level": "optional", "category": "Observability",
     "description": "Enables exception reporting to Sentry.",
     "sensitive": True, "restart": True},
    {"key": "SENTRY_ENV", "level": "optional", "category": "Observability",
     "description": "Environment label sent with each Sentry event (e.g. 'production').",
     "sensitive": False, "restart": True},

    # ---- VELO Master integration ----
    {"key": "VELO_MASTER_URL", "level": "optional", "category": "VELO Master",
     "description": "Base URL of the VELO Master orchestrator. Without this the install runs standalone.",
     "sensitive": False, "restart": True},
    {"key": "VELO_AGENT_KEY", "level": "optional", "category": "VELO Master",
     "description": "Shared secret authenticating this install to VELO Master.",
     "sensitive": True, "restart": True},
    {"key": "SITE_URL", "level": "optional", "category": "VELO Master",
     "description": "URL VELO Master should call back to. Falls back to PUBLIC_BASE_URL or REPLIT_DOMAINS.",
     "sensitive": False, "restart": False},
]

# Fast lookup by key name.
_KNOWN_BY_KEY: dict[str, dict] = {v["key"]: v for v in KNOWN_VARS}


# ---------------------------------------------------------------------------
# .env file parser / writer
# ---------------------------------------------------------------------------

# Match KEY=VALUE lines. Allows surrounding whitespace and an optional
# 'export ' prefix (some shell-format .env files include it). Value
# may be unquoted, single-quoted, or double-quoted.
_ENV_LINE_RE = re.compile(
    r"""^\s*
        (?:export\s+)?
        ([A-Za-z_][A-Za-z0-9_]*)   # 1: key
        \s*=\s*
        (?:
            "((?:[^"\\]|\\.)*)"    # 2: double-quoted value (allows escapes)
          | '([^']*)'              # 3: single-quoted value (raw)
          | ([^\#\r\n]*?)          # 4: bare value (stop at comment or newline)
        )
        \s*
        (?:\#.*)?                  # trailing comment
        $""",
    re.VERBOSE,
)


def _parse_env_file(path: str | None = None) -> dict[str, str]:
    """Parse a ``.env`` file into a dict. Returns ``{}`` if the file
    does not exist. Malformed lines are silently skipped (we don't
    raise — the file is admin-edited).

    ``path`` is resolved at call time (not as a function-definition
    default) so tests can monkeypatch ``ENV_FILE_PATH`` and have the
    new value picked up by the internal helpers too."""
    if path is None:
        path = ENV_FILE_PATH
    result: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n").rstrip("\r")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = _ENV_LINE_RE.match(line)
                if not m:
                    continue
                key = m.group(1)
                # group 2 = double-quoted, 3 = single-quoted, 4 = bare
                if m.group(2) is not None:
                    # Unescape \" \\ \n \t in double-quoted strings.
                    val = (m.group(2)
                           .replace("\\\\", "\x00")
                           .replace('\\"', '"')
                           .replace("\\n", "\n")
                           .replace("\\t", "\t")
                           .replace("\x00", "\\"))
                elif m.group(3) is not None:
                    val = m.group(3)
                else:
                    val = (m.group(4) or "").strip()
                result[key] = val
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    return result


def _serialise_env_value(value: str) -> str:
    """Format a value for inclusion in a .env file. Wraps in double
    quotes if the value contains whitespace, quotes, or other
    metacharacters that would confuse a shell-style parser."""
    if value == "":
        return '""'
    if re.search(r'[\s"\'#=$`\\]', value):
        escaped = (value
                   .replace("\\", "\\\\")
                   .replace('"', '\\"')
                   .replace("\n", "\\n")
                   .replace("\t", "\\t"))
        return f'"{escaped}"'
    return value


def _write_env_file_atomic(data: dict[str, str], path: str | None = None) -> None:
    """Write ``data`` to the .env file atomically. Sorts keys for
    stable diffs. Uses tempfile + os.replace so a crash mid-write
    cannot leave a half-written file. ``path`` resolved at call time
    so monkeypatching ``ENV_FILE_PATH`` works in tests."""
    if path is None:
        path = ENV_FILE_PATH
    lines = [
        "# Managed by the admin Secrets tab. Hand-edits are preserved on next",
        "# write only if they use the standard KEY=VALUE format.",
        "",
    ]
    for key in sorted(data.keys()):
        lines.append(f"{key}={_serialise_env_value(data[key])}")
    body = "\n".join(lines) + "\n"

    dirpath = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        # Restrictive permissions: secrets are readable only by the
        # owning user. (No-op on non-POSIX but harmless.)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

# Module-private cache: which keys are *currently effective* from the
# .env file. A key lives in here only when ``os.environ[key]`` was put
# there by us (the loader or a subsequent ``set_var``). It is NOT in
# here when ``.env`` parses the key but a Replit Secret / shell export
# was already present and shadowed it — in that case the runtime value
# is from Replit, so the key's effective source is ``replit_secret``.
#
# Why this matters: ``set_var`` refuses to overwrite a Replit-managed
# key (silent no-op would otherwise look like a bug because the loader
# wouldn't apply the new .env value either), and ``unset_var`` MUST
# NOT pop a Replit-provided value out of ``os.environ``. Both rely on
# ``_classify_source`` returning ``replit_secret`` for shadowed keys.
_env_file_keys: set[str] = set()


def load_env_file_into_environ(path: str | None = None) -> int:
    """Called once at app startup. Loads each KEY=VALUE from the
    local ``.env`` file into ``os.environ`` *only* if the key is not
    already set — meaning Replit Secrets / shell-exported vars take
    precedence over the local .env file. Returns the number of keys
    that were applied (for logging).

    Only keys that were actually applied (i.e. were not already in
    ``os.environ``) get tracked in ``_env_file_keys``. Shadowed keys
    deliberately stay out of the set so ``_classify_source`` reports
    them as ``replit_secret`` — see the ``_env_file_keys`` docstring."""
    global _env_file_keys
    parsed = _parse_env_file(path)
    applied: set[str] = set()
    for k, v in parsed.items():
        if k not in os.environ:
            os.environ[k] = v
            applied.add(k)
    _env_file_keys = applied
    return len(applied)


def _mask(value: str) -> str:
    """Mask a sensitive value down to the last 4 chars, prefixed with
    bullet characters. Empty → empty. <=4 chars → all bullets."""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "••••" + value[-4:]


def _classify_source(key: str) -> str:
    """Return where the *currently-effective* value comes from:
    'env_file' → from the local .env (admin can edit here),
    'replit_secret' → from os.environ but NOT in the .env file
                     (admin must edit it through their hosting
                     platform's secret/env-var mechanism — Replit
                     Secrets, Heroku Config Vars, Docker -e flags,
                     systemd EnvironmentFile=, etc),
    'unset'    → not present at all.

    The string ``replit_secret`` is the historical wire-name kept for
    backward compatibility — see ``is_replit_platform()`` for the
    actual host-platform detection used to render the right UI label.
    """
    if key in _env_file_keys:
        return "env_file"
    if os.environ.get(key):
        return "replit_secret"
    return "unset"


def is_replit_platform() -> bool:
    """True iff the running process appears to be on a Replit host.
    Replit injects ``REPL_ID`` (and, for Reserved-VM/Autoscale
    deployments, ``REPLIT_DEPLOYMENT``) into the environment of every
    workspace and deployment. This is purely a UX hint so the admin
    Secrets tab can label a platform-managed var as "Replit Secret"
    on Replit and "Environment" elsewhere — the underlying behavior
    (precedence, lock-from-edit) is identical on every host."""
    return bool(os.environ.get("REPL_ID") or os.environ.get("REPLIT_DEPLOYMENT"))


def get_status() -> list[dict]:
    """Return one row per known var, sorted by category then key.
    Each row carries: key, category, level, description, sensitive,
    restart, url, set, source, masked, value (only for non-sensitive
    set vars). Never returns a sensitive value in clear."""
    rows: list[dict] = []
    for meta in KNOWN_VARS:
        key = meta["key"]
        raw = os.environ.get(key, "")
        is_set = bool(raw)
        source = _classify_source(key)
        row = {
            "key": key,
            "category": meta["category"],
            "level": meta["level"],
            "description": meta["description"],
            "sensitive": meta["sensitive"],
            "restart": meta["restart"],
            "url": meta.get("url", ""),
            "set": is_set,
            "source": source,
            "masked": _mask(raw) if (is_set and meta["sensitive"]) else "",
            # Only show the clear value for explicitly non-sensitive
            # config (URLs, emails, phone numbers, plain flags).
            "value": raw if (is_set and not meta["sensitive"]) else "",
        }
        rows.append(row)
    rows.sort(key=lambda r: (r["category"], r["key"]))
    return rows


class EnvManagerError(Exception):
    """Raised by set_var / unset_var on validation failure. Caller
    should map this to a 4xx response with .args[0] as the message."""


def set_var(key: str, value: str) -> dict:
    """Write ``key=value`` into the local .env file and refresh
    ``os.environ`` so the running process sees the new value
    immediately.

    Validation:
    * ``key`` must be in the curated whitelist.
    * If a *Replit Secret* (or shell export) is currently providing
      this key, REJECT — writing to .env wouldn't take effect because
      ``load_env_file_into_environ`` won't override an already-set
      var. Tell the caller to remove the Replit Secret first.
    * ``value`` must be a string ≤8KB and contain no NUL bytes.
    * Empty string is allowed (treat as 'set to empty', distinct from
      unset). Useful for FORCE_SECURE_COOKIES="" to disable.

    Returns the updated row from ``get_status()``."""
    if key not in _KNOWN_BY_KEY:
        raise EnvManagerError(f"Unknown key: {key!r}. Only whitelisted env vars can be set here.")
    if not isinstance(value, str):
        raise EnvManagerError("Value must be a string.")
    if "\x00" in value:
        raise EnvManagerError("Value contains NUL bytes.")
    if len(value) > 8192:
        raise EnvManagerError("Value too long (max 8KB).")
    # Reject if a non-.env source (Replit Secret / shell) is currently
    # shadowing this key — writing to .env would silently no-op.
    current_source = _classify_source(key)
    if current_source == "replit_secret":
        # Host-aware wording: only call out "Replit Secrets" when we're
        # actually running on Replit; otherwise refer generically to
        # the hosting platform (Heroku Config Vars, Railway, Fly,
        # Docker -e, systemd EnvironmentFile=, etc).
        where = "Replit Secrets pane" if is_replit_platform() else "your hosting platform's environment configuration"
        raise EnvManagerError(
            f"{key} is currently provided by the host environment and cannot "
            f"be overridden from the .env file. Update or remove it in "
            f"{where} first, then set it here."
        )

    # Read current .env, merge, write atomically.
    data = _parse_env_file()
    data[key] = value
    _write_env_file_atomic(data)
    # Refresh in-process env: this var is now from the .env file.
    _env_file_keys.add(key)
    os.environ[key] = value
    return _get_one_status(key)


def unset_var(key: str) -> dict:
    """Remove ``key`` from the local .env file and from
    ``os.environ`` (if it came from .env). If the key is currently
    provided by a Replit Secret, REJECT — we can't delete a Replit
    Secret from inside the app.

    Returns the updated row from ``get_status()``."""
    if key not in _KNOWN_BY_KEY:
        raise EnvManagerError(f"Unknown key: {key!r}.")
    source = _classify_source(key)
    if source == "replit_secret":
        where = "Replit Secrets pane" if is_replit_platform() else "your hosting platform's environment configuration"
        raise EnvManagerError(
            f"{key} is provided by the host environment, not the .env file. "
            f"Remove it from {where} to unset it."
        )
    if source == "unset":
        # Idempotent: already unset.
        return _get_one_status(key)

    data = _parse_env_file()
    data.pop(key, None)
    _write_env_file_atomic(data)
    _env_file_keys.discard(key)
    os.environ.pop(key, None)
    return _get_one_status(key)


def _get_one_status(key: str) -> dict:
    """Helper: re-read status for a single key (used by set/unset)."""
    for row in get_status():
        if row["key"] == key:
            return row
    return {"key": key, "set": False, "source": "unset"}


def known_keys() -> Iterable[str]:
    """Iterator over every whitelisted key name."""
    return (v["key"] for v in KNOWN_VARS)
