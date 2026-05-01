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
    python scripts/snapshot.py --include-admin                # include admin AI / skills / MCPs / dashboards / etc.
    python scripts/snapshot.py --include-admin --include-admin-secrets  # also include MCP credentials & webhook tokens
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
import uuid
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

# Tier 6: which _SETTINGS_TABLES keys are actually admin-side singletons
# (registered there for DRY UPSERT routing through update_settings, but
# semantically NOT part of the customer-facing settings group). We filter
# these out of the default snapshot so a normal customer-content snapshot
# doesn't quietly carry the agency's admin AI / automation policy
# alongside. They get included only when --include-admin is passed.
_ADMIN_SINGLETON_KEYS = ("agent_provider_settings", "automation_settings")


def _json_default(obj: Any) -> Any:
    """JSON encoder fallback for psycopg2 row values that don't natively
    serialize: datetimes, dates, Decimals, memoryviews, UUIDs."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        # Use float for portability; bootstrap_install applies via update_*
        # which casts back to numeric/jsonb as needed.
        return float(obj)
    if isinstance(obj, uuid.UUID):
        # Postgres uuid columns come back as uuid.UUID via psycopg2 — must
        # be serialized as their canonical hex string. (No current admin
        # table uses uuid columns, but several content tables do, e.g.
        # site_visitors.id; safer to handle here than to find out at
        # download-time when content export is enabled.)
        return str(obj)
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


def read_settings(conn, cursor_factory, tenant_id: int, errors: list[str],
                  include_admin: bool = False) -> tuple[dict, dict]:
    """Read each _SETTINGS_TABLES entry and emit two dicts:
        (customer_settings, admin_settings)
    matching the bootstrap_install template shape: {settings_key: {col: value, ...}}.

    Customer settings always go in customer_settings. Admin singletons (those
    listed in _ADMIN_SINGLETON_KEYS) go in admin_settings — but only when
    include_admin=True. When include_admin=False they're skipped entirely so
    a customer-content snapshot never quietly leaks the agency's admin AI
    config to a client.

    Skips empty/missing rows silently (not every install populates every
    settings table). Multiple settings keys can map to the same physical
    table (site_settings + business_info both live on `site_settings`);
    we read each key with its own SELECT so the safelisted column set is
    respected.
    """
    from velo_handlers import _SETTINGS_TABLES

    customer_out: dict[str, dict] = {}
    admin_out: dict[str, dict] = {}
    for key, (table, columns) in _SETTINGS_TABLES.items():
        is_admin = key in _ADMIN_SINGLETON_KEYS
        if is_admin and not include_admin:
            continue
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
            if not cleaned:
                continue
            if is_admin:
                admin_out[key] = cleaned
            else:
                customer_out[key] = cleaned
        except Exception as e:
            errors.append(f"settings.{key}: {type(e).__name__}: {e}")
    return customer_out, admin_out


def read_admin_records(conn, cursor_factory, errors: list[str],
                       include_secrets: bool = False) -> dict:
    """Tier 6: read each _ADMIN_RECORD_TABLES entry as a list of dicts and
    emit a top-level `admin_records` block. bootstrap_install will UPSERT
    each row by its natural key (meta['key_cols']) so re-applying the same
    snapshot on a master+clients fleet updates existing rows in place.

    Sensitive columns (mcp_servers.auth_credential, oauth_state;
    custom_webhook_skills.headers_json; automations.webhook_token) are
    redacted unless include_secrets=True. Operational columns
    (last_run_at, last_test_at, etc.) and id/timestamps are always
    stripped — those are per-install state, not template content.

    Tables with `children` metadata (currently just dashboards →
    dashboard_widgets) get their child rows nested under each parent
    keyed by the child's logical_key. The FK column is not emitted in
    the snapshot — bootstrap_install resolves it back from the parent's
    name on import. This way snapshot files survive moving across
    installs where dashboards.id sequences differ.
    """
    from velo_handlers import _ADMIN_RECORD_TABLES

    def _read_table(meta, parent_id_col=None, parent_id_val=None):
        table = meta["table"]
        sensitive = meta.get("sensitive_cols", set())
        drop = meta.get("drop_cols", set()) | _STRIP_COLS
        # Discover real columns via information_schema so future schema
        # additions are picked up automatically without editing this script.
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name = %s",
                (table,),
            )
            all_cols = [r["column_name"] for r in cur.fetchall()]
        keep_cols = [c for c in all_cols if c not in drop]
        if not include_secrets:
            keep_cols = [c for c in keep_cols if c not in sensitive]
        if not keep_cols:
            return []
        col_list = ", ".join(keep_cols)
        if parent_id_col is not None:
            sql = (f"SELECT {col_list} FROM {table} "
                   f"WHERE {parent_id_col} = %s ORDER BY 1")
            args: tuple = (parent_id_val,)
        else:
            sql = f"SELECT {col_list} FROM {table} ORDER BY 1"
            args = ()
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        # Drop None values per-row (same reason as read_settings).
        return [{k: v for k, v in r.items() if v is not None} for r in rows]

    out: dict[str, list[dict]] = {}
    for logical_key, meta in _ADMIN_RECORD_TABLES.items():
        try:
            parent_rows = _read_table(meta)
            if not parent_rows:
                continue
            children_meta = meta.get("children", [])
            if children_meta:
                # We need each parent's id to read its children — but we
                # stripped id from the projection above. Re-fetch (id, key_cols)
                # so we can pair them up. Cheap because the parent table
                # is always small (dashboards = handful of rows). ORDER BY
                # id ASC matches the import-side _upsert_admin_record's
                # tie-breaker (lowest-id wins), so on a parent table with
                # duplicate-name rows the snapshot scopes children to the
                # same canonical parent that import will resolve to.
                with conn.cursor(cursor_factory=cursor_factory) as cur:
                    key_cols = meta["key_cols"]
                    cur.execute(
                        f"SELECT id, {', '.join(key_cols)} "
                        f"FROM {meta['table']} ORDER BY id ASC"
                    )
                    id_map: dict = {}
                    for r in cur.fetchall():
                        id_map.setdefault(
                            tuple(r[k] for k in key_cols), r["id"]
                        )  # setdefault preserves the LOWEST id on dup keys
                for parent_row in parent_rows:
                    parent_key = tuple(parent_row.get(k) for k in meta["key_cols"])
                    parent_id = id_map.get(parent_key)
                    if parent_id is None:
                        # Should be impossible — every parent_row came
                        # from the same SELECT we just re-ran. Surface
                        # it explicitly instead of silently dropping
                        # this parent's children, which would be a real
                        # data-loss bug to debug later.
                        errors.append(
                            f"admin_records.{logical_key}: parent id "
                            f"remap miss for key={parent_key} "
                            f"(child rows skipped)"
                        )
                        continue
                    for ch in children_meta:
                        children = _read_table(
                            ch, parent_id_col=ch["fk_col"],
                            parent_id_val=parent_id,
                        )
                        if children:
                            parent_row[ch["logical_key"]] = children
            out[logical_key] = parent_rows
        except Exception as e:
            errors.append(f"admin_records.{logical_key}: "
                          f"{type(e).__name__}: {e}")
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

        customer_settings, admin_settings = read_settings(
            conn, cursor_factory, args.tenant_id, errors,
            include_admin=args.include_admin,
        )
        if customer_settings:
            snapshot["settings"] = customer_settings
        # Admin singletons go into the same `settings` block — bootstrap_install
        # routes them through update_settings exactly like customer settings,
        # but they're conceptually distinct so we only emit them when the
        # operator opted in via --include-admin.
        if admin_settings:
            snapshot.setdefault("settings", {}).update(admin_settings)

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

        # Tier 6: admin-side multi-row tables (skills, MCPs, dashboards,
        # automations, messaging templates, model prices). Off by default
        # because they're agency-internal; --include-admin opts in.
        # Secrets within those tables (mcp_servers.auth_credential, etc.)
        # require the additional --include-admin-secrets flag — defence
        # against accidentally leaking the master's credentials when
        # someone snapshots without thinking.
        if args.include_admin:
            admin_recs = read_admin_records(
                conn, cursor_factory, errors,
                include_secrets=args.include_admin_secrets,
            )
            if admin_recs:
                snapshot["admin_records"] = admin_recs

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


def summarize(snapshot: dict) -> dict:
    """Reduce a built snapshot to row counts only — used by the admin UI
    preview pane and the `summary_only` mode of the VELO export command.

    Cheap to compute (no extra DB hits) since the snapshot dict already
    has every row in memory. Mirrors the structure the Tier 10 dashboard
    panel expects: settings_keys[], features.{mode,plan,count},
    faqs_count, content_counts{}, admin_record_counts{}, exported_at."""
    summary: dict = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "settings_keys": sorted((snapshot.get("settings") or {}).keys()),
        "faqs_count": len(snapshot.get("faqs") or []),
        "content_counts": {},
        "admin_record_counts": {},
    }

    feats = snapshot.get("features") or {}
    if "set" in feats:
        s = feats["set"] or {}
        summary["features"] = {
            "mode": "set",
            "count": sum(1 for v in s.values() if v),
        }
    elif "plan" in feats:
        summary["features"] = {"mode": "plan", "plan": feats["plan"], "count": 0}
    else:
        summary["features"] = {"mode": "none", "count": 0}

    for k, rows in (snapshot.get("content") or {}).items():
        if isinstance(rows, list):
            summary["content_counts"][k] = len(rows)

    for k, rows in (snapshot.get("admin_records") or {}).items():
        if not isinstance(rows, list):
            continue
        counts: dict = {"rows": len(rows)}
        # Detect nested children (Tier 6 — only `dashboards.widgets` today
        # but the structure generalises). Sum across all parent rows so
        # the operator sees the total widget count, not per-parent.
        child_totals: dict = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for ck, cv in row.items():
                if isinstance(cv, list):
                    child_totals[ck] = child_totals.get(ck, 0) + len(cv)
        counts.update(child_totals)
        summary["admin_record_counts"][k] = counts

    return summary


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
    p.add_argument(
        "--include-admin", action="store_true",
        help=(
            "Tier 6: include admin-side data — agent provider settings, "
            "automation policy, agent_skills, custom_sql_skills, "
            "custom_webhook_skills, mcp_servers, automations, messaging "
            "templates, model_prices, dashboards (with widgets nested). "
            "On import these UPSERT by natural key (name) so re-pushing "
            "from a master install updates clients in place."
        ),
    )
    p.add_argument(
        "--include-admin-secrets", action="store_true",
        help=(
            "Also include sensitive admin columns (mcp_servers.auth_credential, "
            "mcp_servers.oauth_state, custom_webhook_skills.headers_json, "
            "automations.webhook_token). Requires --include-admin. Off by "
            "default — cloning credentials across clients is rarely safe."
        ),
    )
    args = p.parse_args(argv)
    if args.include_admin_secrets and not args.include_admin:
        print("ERROR: --include-admin-secrets requires --include-admin",
              file=sys.stderr)
        return 2

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
        # Roll up admin record counts (parents + nested children) for a
        # one-line confirmation that --include-admin actually picked stuff up.
        admin_total = 0
        for parent_rows in snapshot.get("admin_records", {}).values():
            admin_total += len(parent_rows)
            for parent in parent_rows:
                for v in parent.values():
                    if isinstance(v, list):
                        admin_total += len(v)
        admin_part = (f", {admin_total} admin records"
                      if "admin_records" in snapshot else "")
        print(
            f"Wrote snapshot to {args.output} "
            f"({len(text)} bytes, "
            f"{len(snapshot.get('settings', {}))} settings sections, "
            f"{len(snapshot.get('faqs', []))} faqs, "
            f"{sum(len(v) for v in snapshot.get('content', {}).values())} content rows"
            f"{admin_part})",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
