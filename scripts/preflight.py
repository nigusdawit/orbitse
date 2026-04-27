#!/usr/bin/env python3
"""
Preflight doctor for a fresh client install.

Run this on any host (Replit / Render / Fly.io / Railway / VPS / Docker)
right after deploying to confirm the install is healthy. Reports on:

  * Required env vars (DB, AI key, admin password, secret key)
  * Strongly-recommended env vars (public URL, admin email)
  * Schema bootstrap state (table count, /setup wizard marker)
  * Optional integration env vars and which features they enable
  * Replit-only env vars (only checked when running on Replit)

Exit codes:
  0  all required green
  1  at least one required check failed
  2  with --strict, at least one warning was raised

Usage:
  python scripts/preflight.py
  python scripts/preflight.py --json        # machine-readable
  python scripts/preflight.py --strict      # warnings also fail
  python scripts/preflight.py --quiet       # only print failures
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

# Ensure the project root is importable when run as `python scripts/preflight.py`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_INFO = "info"


@dataclass
class CheckResult:
    name: str
    status: str            # ok | warn | fail | info
    message: str
    feature: Optional[str] = None  # what feature this enables/affects
    detail: Optional[str] = None   # extra hint shown in verbose mode


@dataclass
class Report:
    required: list[CheckResult] = field(default_factory=list)
    recommended: list[CheckResult] = field(default_factory=list)
    schema: list[CheckResult] = field(default_factory=list)
    integrations: list[CheckResult] = field(default_factory=list)
    replit: list[CheckResult] = field(default_factory=list)

    def all(self) -> list[CheckResult]:
        return (
            self.required + self.recommended + self.schema +
            self.integrations + self.replit
        )

    def has_failures(self) -> bool:
        return any(c.status == STATUS_FAIL for c in self.all())

    def has_warnings(self) -> bool:
        return any(c.status == STATUS_WARN for c in self.all())


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    return v or None


def _on_replit() -> bool:
    return bool(os.environ.get("REPL_IDENTITY") or os.environ.get("REPLIT_DOMAINS"))


# ---------- check builders ----------

def _classify_db_error(exc: Exception) -> str:
    """Map a DB connection exception to a short, secret-safe summary.

    Avoids echoing the raw exception text because some psycopg2 errors include
    the full DSN (host/user/password) in their message string.
    """
    text = str(exc).lower()
    if "could not translate host" in text or "name or service" in text or "no such host" in text:
        return "host not resolvable (DNS / typo in hostname)"
    if "connection refused" in text:
        return "connection refused (port closed or DB not running)"
    if "timeout" in text or "timed out" in text:
        return "connect timeout (firewall, security group, or wrong port)"
    if "authentication failed" in text or "password authentication" in text:
        return "authentication failed (wrong user/password)"
    if "does not exist" in text and "database" in text:
        return "database name does not exist on the server"
    if "ssl" in text:
        return "SSL/TLS negotiation failed"
    return f"{type(exc).__name__} (run `psql \"$DATABASE_URL\"` to see the full error)"


def check_required(report: Report) -> None:
    # DATABASE_URL must be set and reachable
    db_url = _env("DATABASE_URL")
    if not db_url:
        report.required.append(CheckResult(
            "DATABASE_URL", STATUS_FAIL,
            "not set — the app cannot start without a Postgres connection string",
            detail="Example: postgresql://user:pass@host:5432/dbname",
        ))
    else:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0].split(",")[0]
            conn.close()
            report.required.append(CheckResult(
                "DATABASE_URL", STATUS_OK,
                f"set and reachable ({version})",
            ))
        except Exception as e:
            # Sanitized: never echo the raw exception (some DSN parse / auth
            # errors include host/user/password in their message string).
            report.required.append(CheckResult(
                "DATABASE_URL", STATUS_FAIL,
                f"set but unreachable — {_classify_db_error(e)}",
                detail="Check the host/port/credentials and that the DB is running",
            ))

    # ADMIN_PASSWORD must be customized
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_pw:
        report.required.append(CheckResult(
            "ADMIN_PASSWORD", STATUS_FAIL,
            "not set — admin login will fall back to the default 'admin'",
            detail="Set this to a strong password before exposing the install",
        ))
    elif admin_pw == "admin":
        report.required.append(CheckResult(
            "ADMIN_PASSWORD", STATUS_FAIL,
            "still set to the default 'admin' — this is a security footgun",
            detail="Pick a strong unique password and re-set this env var",
        ))
    else:
        report.required.append(CheckResult(
            "ADMIN_PASSWORD", STATUS_OK,
            f"set (length {len(admin_pw)})",
        ))

    # At least one AI key required for chat to work. Three env-var names are
    # accepted: OPENAI_API_KEY (canonical), AI_INTEGRATIONS_OPENAI_API_KEY
    # (Replit-managed integration), and ANTHROPIC_API_KEY.
    openai = _env("OPENAI_API_KEY") or _env("AI_INTEGRATIONS_OPENAI_API_KEY")
    anthropic = _env("ANTHROPIC_API_KEY")
    if openai and anthropic:
        report.required.append(CheckResult(
            "AI provider key", STATUS_OK,
            "both OpenAI and Anthropic keys present",
        ))
    elif openai:
        report.required.append(CheckResult(
            "AI provider key", STATUS_OK,
            "OpenAI key present (Anthropic missing — fine, single provider works)",
        ))
    elif anthropic:
        report.required.append(CheckResult(
            "AI provider key", STATUS_OK,
            "Anthropic key present (OpenAI missing — fine, single provider works)",
        ))
    else:
        report.required.append(CheckResult(
            "AI provider key", STATUS_FAIL,
            "no AI key set (need OPENAI_API_KEY, AI_INTEGRATIONS_OPENAI_API_KEY, or ANTHROPIC_API_KEY)",
            detail="At least one is required for the chatbot/agent features",
        ))


def check_recommended(report: Report) -> None:
    # FLASK_SECRET_KEY: WARN-not-FAIL because the app self-generates a random
    # key into .flask_secret on first boot if neither is set. Listed here
    # (not in Required) so the exit-code semantics match: missing is degraded
    # (sessions invalidated on restart) but not a hard boot blocker.
    secret_env = _env("FLASK_SECRET_KEY")
    secret_file = os.path.join(_ROOT, ".flask_secret")
    if secret_env:
        report.recommended.append(CheckResult(
            "FLASK_SECRET_KEY", STATUS_OK,
            f"set via env var (length {len(secret_env)})",
            feature="stable session cookies across restarts and across hosts",
        ))
    elif os.path.exists(secret_file):
        report.recommended.append(CheckResult(
            "FLASK_SECRET_KEY", STATUS_WARN,
            "not set as env var, but .flask_secret file exists",
            feature="stable session cookies across restarts and across hosts",
            detail=(
                "App will read the local file. For multi-host deploys, set "
                "FLASK_SECRET_KEY explicitly so sessions survive across nodes."
            ),
        ))
    else:
        report.recommended.append(CheckResult(
            "FLASK_SECRET_KEY", STATUS_WARN,
            "not set and no .flask_secret file found",
            feature="stable session cookies across restarts",
            detail=(
                "App will auto-generate a random key on first boot. Sessions "
                "will be invalidated on every restart until you set this."
            ),
        ))

    site_url = _env("SITE_URL") or _env("PUBLIC_BASE_URL")
    if site_url:
        report.recommended.append(CheckResult(
            "Public URL", STATUS_OK,
            f"set ({site_url})",
            feature="absolute links in email/SMS, webhooks, SEO canonical URLs",
        ))
    elif _env("REPLIT_DOMAINS"):
        report.recommended.append(CheckResult(
            "Public URL", STATUS_OK,
            "deriving from REPLIT_DOMAINS (Replit-managed)",
            feature="absolute links in email/SMS, webhooks, SEO canonical URLs",
        ))
    else:
        report.recommended.append(CheckResult(
            "Public URL", STATUS_WARN,
            "neither SITE_URL nor PUBLIC_BASE_URL set",
            feature="absolute URLs in outbound email/SMS, webhook callbacks",
            detail="Set PUBLIC_BASE_URL to your full https URL (e.g. https://yoursite.com)",
        ))

    if _env("ADMIN_EMAIL"):
        report.recommended.append(CheckResult(
            "ADMIN_EMAIL", STATUS_OK,
            "set",
            feature="admin alerts and operator notifications",
        ))
    else:
        report.recommended.append(CheckResult(
            "ADMIN_EMAIL", STATUS_WARN,
            "not set",
            feature="admin alert emails will have no recipient",
        ))


def check_schema(report: Report) -> None:
    """Each DB probe is independently exception-safe so a partial bootstrap
    (missing tables, missing columns from an older schema) reports cleanly
    instead of crashing the whole script."""
    if not _env("DATABASE_URL"):
        return
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    except Exception:
        return  # already reported by check_required

    try:
        # Probe 1: total table count
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
                n_tables = cur.fetchone()["n"]
            if n_tables >= 50:
                report.schema.append(CheckResult(
                    "Schema bootstrap", STATUS_OK,
                    f"{n_tables} tables present in public schema",
                ))
            elif n_tables == 0:
                report.schema.append(CheckResult(
                    "Schema bootstrap", STATUS_FAIL,
                    "database is empty — app hasn't booted yet",
                    detail="Start the app once (python app.py); it auto-creates the schema on boot",
                ))
                # No point in further probes against an empty DB.
                return
            else:
                report.schema.append(CheckResult(
                    "Schema bootstrap", STATUS_WARN,
                    f"only {n_tables} tables — partial schema (expected ~80+)",
                    detail="The app may have crashed mid-bootstrap. Check the boot log for errors.",
                ))
        except Exception as e:
            report.schema.append(CheckResult(
                "Schema bootstrap", STATUS_WARN,
                f"could not query information_schema: {type(e).__name__}",
                detail="Tables can't be counted — DB role may lack SELECT on information_schema",
            ))
            return

        # Probe 2: site_settings + install marker (Tier 3 wizard state).
        # Wrapped because `site_settings` may not exist on a fresh-out-of-the-box
        # DB and `installation_bootstrapped_at` is a Tier-3-era column that
        # won't exist on pre-Tier-3 schemas.
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT installation_bootstrapped_at, site_name "
                    "FROM site_settings WHERE id = 1"
                )
                row = cur.fetchone()
            if row is None:
                report.schema.append(CheckResult(
                    "Install state", STATUS_WARN,
                    "no row in site_settings — the app hasn't fully initialized",
                ))
            elif row.get("installation_bootstrapped_at"):
                ts = row["installation_bootstrapped_at"]
                report.schema.append(CheckResult(
                    "Install state", STATUS_OK,
                    f"bootstrapped at {ts:%Y-%m-%d %H:%M %Z} (site_name='{row.get('site_name')}')",
                ))
            else:
                report.schema.append(CheckResult(
                    "Install state", STATUS_WARN,
                    "install marker is NULL — first-run wizard hasn't been run yet",
                    detail="Visit /setup in the browser to complete first-run provisioning",
                ))
        except psycopg2.errors.UndefinedTable:
            report.schema.append(CheckResult(
                "Install state", STATUS_WARN,
                "site_settings table missing — boot the app once to auto-create the schema",
            ))
        except psycopg2.errors.UndefinedColumn:
            report.schema.append(CheckResult(
                "Install state", STATUS_WARN,
                "installation_bootstrapped_at column missing — schema predates Tier 3",
                detail="Restart the app to run the boot-time ALTER TABLE that adds this column",
            ))
        except Exception as e:
            report.schema.append(CheckResult(
                "Install state", STATUS_WARN,
                f"could not read install marker: {type(e).__name__}",
            ))

        # Probe 3: customer count. Note: this app's admin auth is a single
        # shared ADMIN_PASSWORD env var (already checked in Required), NOT
        # a per-user admin flag — the customers table here represents the
        # paying-customer / chatbot-user roster, not admins. We surface the
        # row count as info-only so the operator can confirm whether the
        # Tier 2/3 manage_user command (called by the /setup wizard) has
        # ever populated this table.
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) AS n FROM customers")
                n_customers = cur.fetchone()["n"]
            report.schema.append(CheckResult(
                "Customers table", STATUS_OK,
                f"{n_customers} customer(s) registered",
                detail=(
                    "Empty is fine for a fresh install. The /setup wizard "
                    "calls manage_user with the operator's email so this "
                    "row count goes from 0 to 1+ after first-run setup."
                ) if n_customers == 0 else None,
            ))
        except psycopg2.errors.UndefinedTable:
            report.schema.append(CheckResult(
                "Customers table", STATUS_WARN,
                "customers table missing — boot the app once to auto-create the schema",
            ))
        except Exception as e:
            report.schema.append(CheckResult(
                "Customers table", STATUS_WARN,
                f"could not count customers: {type(e).__name__}",
            ))
    finally:
        conn.close()


def check_integrations(report: Report) -> None:
    # Each integration: list of (env vars), feature label
    checks = [
        (["RESEND_API_KEY", "RESEND_FROM_EMAIL"], "outbound email (transactional + alerts)"),
        (["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"], "outbound SMS"),
        (["STRIPE_SECRET_KEY"], "Stripe checkout / storefront"),
        (["STRIPE_WEBHOOK_SECRET"], "Stripe webhook signature verification"),
        (["ELEVENLABS_API_KEY"], "ElevenLabs TTS / voice"),
        (["BRAVE_SEARCH_API_KEY"], "agent web search"),
        (["GOOGLE_PLACES_API_KEY"], "Google review aggregation"),
        (["YELP_API_KEY"], "Yelp review aggregation"),
        (["TRIPADVISOR_API_KEY"], "TripAdvisor review aggregation"),
        (["SENTRY_DSN"], "error reporting (Sentry)"),
        (["ADMIN_PHONE"], "admin alert SMS"),
        (["VELO_MASTER_URL", "VELO_AGENT_KEY"], "VELO cross-site sync"),
        (["RESEND_WEBHOOK_SECRET"], "Resend inbound webhook verification"),
    ]
    for vars_, feature in checks:
        present = [v for v in vars_ if _env(v)]
        missing = [v for v in vars_ if not _env(v)]
        label = " + ".join(vars_)
        if not missing:
            report.integrations.append(CheckResult(
                label, STATUS_OK, "all set",
                feature=feature,
            ))
        elif present:
            report.integrations.append(CheckResult(
                label, STATUS_WARN,
                f"partial: missing {', '.join(missing)}",
                feature=feature,
                detail=f"Set the missing var(s) to enable: {feature}",
            ))
        else:
            report.integrations.append(CheckResult(
                label, STATUS_INFO, "not configured",
                feature=feature,
                detail=f"Optional. Setting these enables: {feature}",
            ))


def check_replit(report: Report) -> None:
    if not _on_replit():
        return  # not on Replit, skip entirely
    if _env("REPL_IDENTITY"):
        report.replit.append(CheckResult(
            "REPL_IDENTITY", STATUS_OK,
            "present (Replit-managed connector auth available)",
        ))
    if _env("REPLIT_DOMAINS"):
        report.replit.append(CheckResult(
            "REPLIT_DOMAINS", STATUS_OK,
            f"set ({_env('REPLIT_DOMAINS')[:60]}…)" if len(_env("REPLIT_DOMAINS") or "") > 60
            else f"set ({_env('REPLIT_DOMAINS')})",
        ))
    if _env("REPLIT_DEPLOYMENT") == "1":
        report.replit.append(CheckResult(
            "REPLIT_DEPLOYMENT", STATUS_OK,
            "running on a Replit Deployment (production mode)",
        ))


# ---------- output formatters ----------

ICON = {
    STATUS_OK: "[ OK ]",
    STATUS_WARN: "[WARN]",
    STATUS_FAIL: "[FAIL]",
    STATUS_INFO: "[ -- ]",
}

def _color(text: str, status: str, use_color: bool) -> str:
    if not use_color:
        return text
    codes = {
        STATUS_OK:   "\033[32m",  # green
        STATUS_WARN: "\033[33m",  # yellow
        STATUS_FAIL: "\033[31m",  # red
        STATUS_INFO: "\033[90m",  # gray
    }
    reset = "\033[0m"
    return f"{codes.get(status, '')}{text}{reset}"


def _print_section(title: str, checks: list[CheckResult], opts) -> None:
    if not checks:
        return
    if opts.quiet:
        # Only show non-OK in quiet mode
        checks = [c for c in checks if c.status in (STATUS_WARN, STATUS_FAIL)]
        if not checks:
            return
    print(f"\n── {title} " + "─" * (60 - len(title)))
    for c in checks:
        icon = _color(ICON[c.status], c.status, opts.color)
        line = f"  {icon}  {c.name}: {c.message}"
        print(line)
        if c.feature and (opts.verbose or c.status in (STATUS_WARN, STATUS_FAIL)):
            print(f"          ↳ feature: {c.feature}")
        if c.detail and (opts.verbose or c.status in (STATUS_WARN, STATUS_FAIL)):
            print(f"          ↳ {c.detail}")


def _print_summary(report: Report, opts) -> None:
    n_ok = sum(1 for c in report.all() if c.status == STATUS_OK)
    n_warn = sum(1 for c in report.all() if c.status == STATUS_WARN)
    n_fail = sum(1 for c in report.all() if c.status == STATUS_FAIL)
    n_info = sum(1 for c in report.all() if c.status == STATUS_INFO)

    print("\n" + "=" * 64)
    summary = (
        f"  {_color(f'{n_ok} ok', STATUS_OK, opts.color)}   "
        f"{_color(f'{n_warn} warn', STATUS_WARN, opts.color)}   "
        f"{_color(f'{n_fail} fail', STATUS_FAIL, opts.color)}   "
        f"{n_info} not configured"
    )
    print(summary)
    if n_fail:
        print(_color("\n  ❌  Required checks failed. Fix the [FAIL] items above.",
                     STATUS_FAIL, opts.color))
    elif n_warn and opts.strict:
        print(_color("\n  ⚠️   Warnings present and --strict is on.",
                     STATUS_WARN, opts.color))
    else:
        print(_color("\n  ✅  Install looks healthy.", STATUS_OK, opts.color))
    print()


def _emit_json(report: Report) -> None:
    out = {
        "required": [asdict(c) for c in report.required],
        "recommended": [asdict(c) for c in report.recommended],
        "schema": [asdict(c) for c in report.schema],
        "integrations": [asdict(c) for c in report.integrations],
        "replit": [asdict(c) for c in report.replit],
        "summary": {
            "ok": sum(1 for c in report.all() if c.status == STATUS_OK),
            "warn": sum(1 for c in report.all() if c.status == STATUS_WARN),
            "fail": sum(1 for c in report.all() if c.status == STATUS_FAIL),
            "info": sum(1 for c in report.all() if c.status == STATUS_INFO),
            "healthy": not report.has_failures(),
        },
    }
    print(json.dumps(out, indent=2, default=str))


# ---------- entry point ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight doctor for client install health.")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any warnings")
    parser.add_argument("--quiet", action="store_true", help="only print non-OK results")
    parser.add_argument("--verbose", action="store_true", help="show feature/detail lines for OK results too")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args()

    args.color = (not args.no_color) and sys.stdout.isatty() and not args.json

    report = Report()
    check_required(report)
    check_recommended(report)
    check_schema(report)
    check_integrations(report)
    check_replit(report)

    if args.json:
        _emit_json(report)
    else:
        print(_color("\nPreflight check — client install health", STATUS_INFO, args.color))
        _print_section("Required to boot", report.required, args)
        _print_section("Strongly recommended", report.recommended, args)
        _print_section("Schema & install state", report.schema, args)
        _print_section("Optional integrations", report.integrations, args)
        if report.replit:
            _print_section("Replit-specific", report.replit, args)
        _print_summary(report, args)

    if report.has_failures():
        return 1
    if args.strict and report.has_warnings():
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
