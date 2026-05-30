"""
admin_ai_platform.snapshot
==========================

Snapshot / clone CLI (M20). Export a tenant's **template configuration** (not
runtime/customer data) to a JSON file and re-apply it onto a fresh install — the
way an agency bootstraps a new silo instance from a master template.

  * ``python -m admin_ai_platform.snapshot export snap.json``
  * ``python -m admin_ai_platform.snapshot apply  snap.json``

Both talk to ``DATABASE_URL`` via the package DB layer. Apply is idempotent:
singletons UPSERT by ``id=1``; slug/name-keyed tables UPSERT by their natural key;
content tables with no natural key insert only when the target is empty (so a
re-apply never duplicates).

**Secret redaction:** secret-bearing columns are blanked on export so a snapshot
file is safe to copy around — credentials are provisioned per-instance, never
travel in a clone.
"""

from __future__ import annotations

import json
import sys

from .db import query_db, execute_db

SNAPSHOT_VERSION = 2

# table -> {"strategy": singleton|slug|name|append_if_empty,
#           "key": <natural key col>, "redact": [secret cols]}
_TABLES = {
    "chatbot_settings": {"strategy": "singleton"},
    "agent_provider_settings": {"strategy": "singleton"},
    "voice_settings": {"strategy": "singleton"},
    "business_info": {"strategy": "singleton"},
    "gallery_cards": {"strategy": "slug", "key": "slug"},
    "custom_forms": {"strategy": "slug", "key": "slug"},
    "presentations": {"strategy": "slug", "key": "slug"},
    "agent_skills": {"strategy": "name", "key": "name"},
    "experiences": {"strategy": "append_if_empty"},
    "pricing_seasons": {"strategy": "append_if_empty"},
    "faqs": {"strategy": "append_if_empty"},
    "team_members": {"strategy": "append_if_empty"},
    "testimonials": {"strategy": "append_if_empty"},
}

# Columns blanked on export (never clone a secret). Keyed by table.
_REDACT = {
    "agent_provider_settings": ("openai_api_key", "anthropic_api_key", "api_key"),
}

# Columns never written on apply (DB-managed identity/timestamps).
_SKIP_COLS = {"id", "created_at", "updated_at"}


def export_snapshot() -> dict:
    """Read the snapshot tables from the DB into a JSON-able dict, redacting
    secret columns."""
    out = {"version": SNAPSHOT_VERSION, "tables": {}}
    for table in _TABLES:
        try:
            rows = query_db(f"SELECT * FROM {table}") or []
        except Exception as e:
            print(f"[snapshot] export skip {table}: {e}", file=sys.stderr)
            continue
        redact = _REDACT.get(table, ())
        clean = []
        for r in rows:
            d = dict(r)
            for col in redact:
                if col in d:
                    d[col] = ""
            clean.append(_jsonable(d))
        out["tables"][table] = clean
    return out


def _jsonable(row: dict) -> dict:
    """Coerce non-JSON types (dates/times/Decimal) to strings so json.dumps works."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):          # date/datetime/time
            out[k] = v.isoformat()
        elif isinstance(v, (dict, list, str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _insert_cols(table, row):
    """(columns, placeholders, values) for an INSERT, skipping identity columns
    and JSON-encoding dict/list values."""
    cols, ph, vals = [], [], []
    for k, v in row.items():
        if k in _SKIP_COLS:
            continue
        cols.append(k)
        if isinstance(v, (dict, list)):
            ph.append("%s::jsonb")
            vals.append(json.dumps(v))
        else:
            ph.append("%s")
            vals.append(v)
    return cols, ph, vals


def apply_snapshot(snap: dict) -> dict:
    """Apply a snapshot dict onto the current DB. Returns per-table counts."""
    applied = {}
    tables = (snap or {}).get("tables", {})
    for table, spec in _TABLES.items():
        rows = tables.get(table) or []
        if not rows:
            continue
        n = 0
        strat = spec["strategy"]
        if strat == "append_if_empty":
            if query_db(f"SELECT 1 FROM {table} LIMIT 1", fetchone=True):
                applied[table] = "skipped (not empty)"
                continue
        for row in rows:
            try:
                if strat == "singleton":
                    _apply_singleton(table, row)
                elif strat in ("slug", "name"):
                    _apply_upsert(table, row, spec["key"])
                else:  # append_if_empty
                    cols, ph, vals = _insert_cols(table, row)
                    execute_db(f"INSERT INTO {table} ({', '.join(cols)}) "
                               f"VALUES ({', '.join(ph)})", tuple(vals))
                n += 1
            except Exception as e:
                print(f"[snapshot] apply {table} row skipped: {e}", file=sys.stderr)
        applied[table] = n
    return applied


def _apply_singleton(table, row):
    cols, _, vals = _insert_cols(table, row)
    sets = ", ".join(f"{c}=%s" for c in cols)
    execute_db(f"UPDATE {table} SET {sets} WHERE id=1", tuple(vals))
    execute_db(f"INSERT INTO {table} (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # Re-apply in case the row didn't exist yet.
    execute_db(f"UPDATE {table} SET {sets} WHERE id=1", tuple(vals))


def _apply_upsert(table, row, key):
    cols, ph, vals = _insert_cols(table, row)
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != key)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(ph)}) "
           f"ON CONFLICT ({key}) DO UPDATE SET {updates}" if updates
           else f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(ph)}) "
                f"ON CONFLICT ({key}) DO NOTHING")
    execute_db(sql, tuple(vals))


def _main(argv):
    if len(argv) < 2 or argv[0] not in ("export", "apply"):
        print("usage: python -m admin_ai_platform.snapshot export|apply <file.json>")
        return 2
    cmd, path = argv[0], argv[1]
    if cmd == "export":
        snap = export_snapshot()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=2)
        total = sum(len(v) for v in snap["tables"].values())
        print(f"[snapshot] exported {total} rows across {len(snap['tables'])} tables → {path}")
        return 0
    with open(path, encoding="utf-8") as fh:
        snap = json.load(fh)
    applied = apply_snapshot(snap)
    print(f"[snapshot] applied: {applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
