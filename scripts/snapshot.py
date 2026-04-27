#!/usr/bin/env python3
"""
snapshot.py — export this install's settings/features/faqs/content as a
JSON template that can be fed back into bootstrap_install (Tier 2) or
the /setup wizard (Tier 3) on a fresh install.

This is the "clone an existing client to a new client" tool. Run it
against a working install, save the JSON, then on a fresh install
either:
    • paste the JSON into the /setup wizard's preset dropdown, or
    • POST it to bootstrap_install via the VELO command surface.

The output shape matches the existing presets in onboarding_templates/
exactly, so a snapshot drops in wherever a preset would.

Usage:
    python scripts/snapshot.py                          # to stdout
    python scripts/snapshot.py -o my-client.json
    python scripts/snapshot.py --pretty -o pretty.json
    python scripts/snapshot.py --include-content              # include services + team
    python scripts/snapshot.py --include-content=blog,services
    python scripts/snapshot.py --include-all-content
    python scripts/snapshot.py --no-content                   # explicit opt-out
    python scripts/snapshot.py --include-admin-user           # include first customer's email/name
    python scripts/snapshot.py --tenant-id 1                  # which tenant to snapshot

Exit codes:
    0  snapshot written successfully
    1  DATABASE_URL not set or not reachable (no JSON written to stdout/file)
    2  partial snapshot — JSON was still written but one or more sections
       raised errors (warnings echoed to stderr; check them before relying
       on the output for a clone)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date
from decimal import Decimal
from typing import Any

# Make the project root importable so we can pull the column whitelists
# from velo_handlers without re-defining them here.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Default content types to include when --include-content is passed without
# an explicit list. Picked because they're the most "template-y": services
# and team profiles describe what the business does and who runs it, which
# is exactly the kind of structured baseline an agency wants to clone.
# Blog posts, events, products, testimonials, etc. are tenant-specific and
# usually shouldn't be cloned, so they require explicit opt-in.
_DEFAULT_CONTENT_TYPES = ("services", "team")

# Columns we always strip from content rows because they're auto-generated
# by Postgres and would conflict with the target install's sequences /
# uniqueness constraints if re-applied.
_STRIP_COLS = {"id", "created_at", "updated_at"}


def _json_default(obj: Any) -> Any:
    """JSON encoder fallback for psycopg2 row values that don't natively
    serialize: datetimes, dates, Decimals, memoryviews."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        # Use float for portability; bootstrap_install applies via update_*
        # which casts back to numeric/jsonb as needed.
        return float(obj)
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj).decode("utf-8", errors="replace")
    raise TypeError(f"unserializable type: {type(obj).__name__}")


def _connect():
    """Open a single read-only psycopg2 connection. Raises on failure."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(url, connect_timeout=5)
    conn.set_session(readonly=True)
    return conn, RealDictCursor


# ---------- per-section readers ----------


def read_settings(conn, cursor_factory, tenant_id: int, errors: list[str]) -> dict:
    """Read each _SETTINGS_TABLES entry and emit a dict matching the
    bootstrap_install template shape: {settings_key: {col: value, ...}}.

    Skips empty/missing rows silently (not every install populates every
    settings table). Multiple settings keys can map to the same physical
    table (site_settings + business_info both live on `site_settings`);
    we read each key with its own SELECT so the safelisted column set is
    respected.
    """
    from velo_handlers import _SETTINGS_TABLES

    out: dict[str, dict] = {}
    for key, (table, columns) in _SETTINGS_TABLES.items():
        col_list = ", ".join(sorted(columns))
        try:
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                # Singleton settings rows live at id=1. tenant_id is not
                # part of the singleton key in this codebase — settings
                # are global per-install, not per-tenant.
                cur.execute(f"SELECT {col_list} FROM {table} WHERE id = 1")
                row = cur.fetchone()
            if not row:
                continue
            # Drop None values — leaving them in would overwrite preset
            # defaults on the target install with explicit nulls. The
            # operator can re-set them post-clone if needed.
            cleaned = {k: v for k, v in row.items() if v is not None}
            if cleaned:
                out[key] = cleaned
        except Exception as e:
            errors.append(f"settings.{key}: {type(e).__name__}: {e}")
    return out


def read_features(conn, cursor_factory, tenant_id: int, errors: list[str]) -> dict | None:
    """Read tenant_features for the given tenant and emit a `features.set`
    dict (flat name → bool). We use `set` rather than `plan` because we
    can't reliably reverse-engineer which plan was applied — the operator
    may have toggled individual features after applying a plan, and `set`
    captures the actual current state with no ambiguity."""
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(
                "SELECT feature_name, enabled FROM tenant_features "
                "WHERE tenant_id = %s ORDER BY feature_name",
                (tenant_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        errors.append(f"features: {type(e).__name__}: {e}")
        return None

    if not rows:
        return None
    return {"set": {r["feature_name"]: bool(r["enabled"]) for r in rows}}


def read_faqs(conn, cursor_factory, errors: list[str]) -> list[dict]:
    """Read every FAQ as a list of {question, answer, sort_order} dicts.
    bootstrap_install dedupes on question text on re-apply, so re-running
    a snapshot against an install with overlapping FAQs is safe."""
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(
                "SELECT question, answer, sort_order FROM faqs "
                "ORDER BY sort_order, id"
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        errors.append(f"faqs: {type(e).__name__}: {e}")
        return []


def read_admin_user(conn, cursor_factory, errors: list[str]) -> dict | None:
    """Pick the first customer (lowest id) as the admin-user proxy. The
    customers table has no per-row admin flag in this app's auth model
    (admin auth is the shared ADMIN_PASSWORD env var), so we use ordinal
    priority. Operators who care about this should override on the target
    install or rely on the wizard's owner-email form field instead."""
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(
                "SELECT email, name FROM customers ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
        if not row or not row.get("email"):
            return None
        return {"email": row["email"], "name": row.get("name") or ""}
    except Exception as e:
        errors.append(f"admin_user: {type(e).__name__}: {e}")
        return None


def read_content(conn, cursor_factory, types: list[str], errors: list[str]) -> dict:
    """For each requested content_type, SELECT every row and emit it as
    a list of column-value dicts (id/created_at/updated_at stripped).
    bootstrap_install's content path is INSERT-only, so re-applying a
    snapshot against a non-empty install will create duplicate rows;
    that's why content is opt-in, not default."""
    from velo_handlers import _CONTENT_TABLES

    out: dict[str, list[dict]] = {}
    for ct in types:
        info = _CONTENT_TABLES.get(ct)
        if not info:
            errors.append(f"content.{ct}: unknown content type")
            continue
        table = info[0]
        try:
            # Pull the live column list from information_schema so we
            # don't have to hard-code each table's shape and so any
            # future schema additions are picked up automatically.
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    (table,),
                )
                all_cols = [r["column_name"] for r in cur.fetchall()]
            keep_cols = [c for c in all_cols if c not in _STRIP_COLS]
            if not keep_cols:
                errors.append(f"content.{ct}: no exportable columns")
                continue
            col_list = ", ".join(keep_cols)
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                cur.execute(f"SELECT {col_list} FROM {table} ORDER BY 1")
                rows = cur.fetchall()
            # Drop None-valued columns row-by-row so target install gets
            # bootstrap_install's update_content auto-discovery handle
            # defaults rather than explicit nulls.
            cleaned = []
            for r in rows:
                cleaned.append({k: v for k, v in r.items() if v is not None})
            if cleaned:
                out[ct] = cleaned
        except Exception as e:
            errors.append(f"content.{ct}: {type(e).__name__}: {e}")
    return out


# ---------- assembly + CLI ----------


def build_snapshot(args) -> tuple[dict, list[str]]:
    """Top-level orchestrator: open one connection, dispatch to each
    section reader, assemble the final dict in the same key order as the
    existing presets so diffing snapshots stays sane."""
    errors: list[str] = []
    try:
        conn, cursor_factory = _connect()
    except Exception as e:
        # Fatal — without a DB connection we can't snapshot anything.
        errors.append(f"connect: {type(e).__name__}: {e}")
        return {}, errors

    try:
        snapshot: dict = {
            "$schema_version": 1,
            "$description": (
                f"Snapshot of install at {datetime.utcnow().isoformat()}Z "
                f"(tenant_id={args.tenant_id}). Apply via bootstrap_install "
                f"or the /setup wizard."
            ),
        }

        settings = read_settings(conn, cursor_factory, args.tenant_id, errors)
        if settings:
            snapshot["settings"] = settings

        features = read_features(conn, cursor_factory, args.tenant_id, errors)
        if features:
            snapshot["features"] = features

        faqs = read_faqs(conn, cursor_factory, errors)
        if faqs:
            snapshot["faqs"] = faqs

        if args.include_admin_user:
            au = read_admin_user(conn, cursor_factory, errors)
            if au:
                snapshot["admin_user"] = au

        # Resolve which content types to include. CLI semantics:
        #   --no-content                       → []
        #   (no flag at all)                   → []  (default = no content)
        #   --include-content                  → defaults (services, team)
        #   --include-content=services,team    → as listed
        #   --include-all-content              → every key
        if args.no_content:
            content_types: list[str] = []
        elif args.include_all_content:
            from velo_handlers import _CONTENT_TABLES
            content_types = sorted(_CONTENT_TABLES.keys())
        elif args.include_content is not None:
            if args.include_content == "":
                content_types = list(_DEFAULT_CONTENT_TYPES)
            else:
                content_types = [
                    s.strip() for s in args.include_content.split(",") if s.strip()
                ]
        else:
            content_types = []

        if content_types:
            content = read_content(conn, cursor_factory, content_types, errors)
            if content:
                snapshot["content"] = content

        return snapshot, errors
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="snapshot.py",
        description=(
            "Export this install's template-relevant state (settings, "
            "features, faqs, optionally content + admin user) as JSON "
            "for cloning to a fresh install."
        ),
    )
    p.add_argument(
        "-o", "--output", metavar="FILE",
        help="Write JSON to FILE instead of stdout",
    )
    p.add_argument(
        "--pretty", action="store_true",
        help="Pretty-print with 2-space indent (default: compact)",
    )
    p.add_argument(
        "--tenant-id", type=int, default=1, metavar="N",
        help="Which tenant_id to snapshot features for (default: 1)",
    )
    # Content selection — three mutually-informative flags. argparse
    # doesn't enforce mutex here so the precedence is documented in
    # build_snapshot (--no-content > --include-all-content > --include-content).
    p.add_argument(
        "--include-content", nargs="?", const="", default=None, metavar="TYPES",
        help=(
            "Include content. Pass with no value to include defaults "
            f"({','.join(_DEFAULT_CONTENT_TYPES)}), or with a comma-separated "
            "list of types (blog, events, products, services, testimonials, "
            "team, gallery, video, podcast, pages)."
        ),
    )
    p.add_argument(
        "--include-all-content", action="store_true",
        help="Include every content type (overrides --include-content)",
    )
    p.add_argument(
        "--no-content", action="store_true",
        help="Explicitly exclude content (default behavior; this flag wins over the others)",
    )
    p.add_argument(
        "--include-admin-user", action="store_true",
        help=(
            "Include the first customer's email/name as admin_user. "
            "Off by default because admin identity is per-install, not "
            "per-template."
        ),
    )
    args = p.parse_args(argv)

    snapshot, errors = build_snapshot(args)

    # No snapshot at all means we couldn't even connect.
    if not snapshot:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    # Echo non-fatal errors to stderr so they're visible without
    # corrupting the JSON on stdout / in the output file.
    for err in errors:
        print(f"WARN: {err}", file=sys.stderr)

    indent = 2 if args.pretty else None
    text = json.dumps(snapshot, indent=indent, default=_json_default,
                      sort_keys=False, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        print(
            f"Wrote snapshot to {args.output} "
            f"({len(text)} bytes, "
            f"{len(snapshot.get('settings', {}))} settings sections, "
            f"{len(snapshot.get('faqs', []))} faqs, "
            f"{sum(len(v) for v in snapshot.get('content', {}).values())} content rows)",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
