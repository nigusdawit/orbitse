"""
admin_ai_platform.admin_tools
============================

Elevated tools for the admin AI assistant + the pending-action approval flow.

Safety posture (ported from the main app's admin agent):
  * **Reads** run immediately. ``admin_run_sql`` is SELECT-only: single
    statement, no semicolons, a forbidden-keyword regex, a 100-row cap, a
    statement_timeout, executed in a transaction that is ALWAYS rolled back so
    even an exotic SELECT-with-side-effects is undone.
  * **Writes** are never executed by the model. ``admin_propose_*`` parks the
    change in ``admin_pending_actions`` with a human-readable preview and
    returns ``awaiting_approval``. The write only runs when the owner approves
    it via the approval route, and only against an allowlisted table with
    column names validated against the live schema (so neither table nor
    column can be an injection vector; values are always parameterized).
"""

from __future__ import annotations

import json
import re

from .db import get_db, query_db, execute_db

# SELECT-only guard: any of these as a word → reject.
_SQL_DANGEROUS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|"
    r"EXECUTE|CALL|MERGE|VACUUM|REINDEX|CLUSTER|REFRESH|LISTEN|NOTIFY|DO|"
    r"SET)\b", re.IGNORECASE)

# Tables the admin assistant may WRITE to (via approved proposals). Everything
# else — cost ledgers, logs, audit, tenant, chat/message, settings singletons —
# is blocked even from an approved action.
ADMIN_WRITABLE_TABLES = {
    "gallery_cards", "presentations", "presentation_slides", "custom_forms",
    "form_fields", "voice_intros", "generated_pages", "agent_skills",
}
_ROW_CAP = 100


def _table_columns(table):
    rows = query_db(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,)) or []
    return rows


def _public_tables():
    rows = query_db("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "ORDER BY tablename") or []
    return [r["tablename"] for r in rows]


# ---- Read tools ---------------------------------------------------------
def admin_list_tables():
    return {"tables": _public_tables()}


def admin_describe_table(table_name=None):
    if not table_name or table_name not in _public_tables():
        return {"error": "unknown table"}
    cols = _table_columns(table_name)
    cnt = query_db(f'SELECT COUNT(*) AS c FROM "{table_name}"', fetchone=True)
    return {"table": table_name, "columns": cols, "row_count": (cnt or {}).get("c", 0)}


def admin_run_sql(sql=None):
    """Run a single read-only SELECT, rolled back, capped at 100 rows."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return {"error": "empty sql"}
    if ";" in sql:
        return {"error": "only a single statement is allowed"}
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return {"error": "only SELECT / WITH ... SELECT is allowed"}
    if _SQL_DANGEROUS.search(sql):
        return {"error": "statement contains a forbidden keyword (read-only only)"}
    conn = get_db()
    try:
        conn.autocommit = False
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = 5000")
            cur.execute(sql)
            rows = cur.fetchmany(_ROW_CAP) if cur.description else []
            return {"rows": [dict(r) for r in rows], "row_count": len(rows),
                    "capped": len(rows) == _ROW_CAP}
    except Exception as e:
        return {"error": str(e)[:300]}
    finally:
        try:
            conn.rollback()
            conn.autocommit = True
        except Exception:
            pass
        conn.close()


def admin_overview_stats():
    def c(sql):
        r = query_db(sql, fetchone=True)
        return (r or {}).get("c", 0)
    return {
        "conversations": c("SELECT COUNT(*) AS c FROM chat_conversations"),
        "form_submissions": c("SELECT COUNT(*) AS c FROM form_submissions"),
        "gallery_cards": c("SELECT COUNT(*) AS c FROM gallery_cards"),
        "generated_pages": c("SELECT COUNT(*) AS c FROM generated_pages"),
        "skills_enabled": c("SELECT COUNT(*) AS c FROM agent_skills WHERE enabled"),
    }


# ---- Write proposals (parked for approval) ------------------------------
def _valid_columns(table):
    return {c["column_name"] for c in _table_columns(table)}


def _park_action(session_id, action_type, table, row_id, fields, preview):
    row = execute_db(
        "INSERT INTO admin_pending_actions (session_id, action_type, target_table, "
        " target_id, payload_json, preview, status) "
        "VALUES (%s,%s,%s,%s,%s::jsonb,%s,'pending') RETURNING id",
        (session_id[:100], action_type, table, row_id,
         json.dumps(fields or {}), preview))
    return {"awaiting_approval": True, "action_id": row["id"] if row else None,
            "preview": preview}


def admin_propose_insert(table_name=None, fields=None, _session_id=""):
    if table_name not in ADMIN_WRITABLE_TABLES:
        return {"error": f"table '{table_name}' is not writable by the assistant"}
    fields = fields or {}
    cols = _valid_columns(table_name)
    bad = [k for k in fields if k not in cols]
    if bad:
        return {"error": f"unknown columns: {bad}"}
    if not fields:
        return {"error": "no fields provided"}
    preview = f"INSERT into {table_name}: " + ", ".join(f"{k}={v!r}" for k, v in fields.items())
    return _park_action(_session_id, "insert", table_name, None, fields, preview)


def admin_propose_update(table_name=None, row_id=None, fields=None, _session_id=""):
    if table_name not in ADMIN_WRITABLE_TABLES:
        return {"error": f"table '{table_name}' is not writable by the assistant"}
    if not row_id:
        return {"error": "row_id required"}
    fields = fields or {}
    cols = _valid_columns(table_name)
    bad = [k for k in fields if k not in cols]
    if bad:
        return {"error": f"unknown columns: {bad}"}
    current = query_db(f'SELECT * FROM "{table_name}" WHERE id=%s', (row_id,), fetchone=True)
    if not current:
        return {"error": f"no row id={row_id} in {table_name}"}
    preview = f"UPDATE {table_name} id={row_id}: " + ", ".join(
        f"{k}: {current.get(k)!r} -> {v!r}" for k, v in fields.items())
    return _park_action(_session_id, "update", table_name, row_id, fields, preview)


def admin_propose_delete(table_name=None, row_id=None, _session_id=""):
    if table_name not in ADMIN_WRITABLE_TABLES:
        return {"error": f"table '{table_name}' is not writable by the assistant"}
    if not row_id:
        return {"error": "row_id required"}
    current = query_db(f'SELECT * FROM "{table_name}" WHERE id=%s', (row_id,), fetchone=True)
    if not current:
        return {"error": f"no row id={row_id} in {table_name}"}
    preview = f"DELETE {table_name} id={row_id} ({dict(current)})"
    return _park_action(_session_id, "delete", table_name, row_id, {}, preview)


# ---- Approval execution -------------------------------------------------
def approve_action(action_id):
    """Execute a parked write inside a transaction. Returns a result dict."""
    act = query_db("SELECT * FROM admin_pending_actions WHERE id=%s", (action_id,), fetchone=True)
    if not act:
        return {"error": "not found"}, 404
    if act["status"] != "pending":
        return {"error": f"already {act['status']}"}, 409
    table = act["target_table"]
    if table not in ADMIN_WRITABLE_TABLES:
        return {"error": "table not writable"}, 400
    cols = _valid_columns(table)
    payload = act.get("payload_json") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    fields = {k: v for k, v in payload.items() if k in cols}  # re-validate columns
    try:
        if act["action_type"] == "insert":
            keys = list(fields.keys())
            ph = ",".join(["%s"] * len(keys))
            colsql = ",".join(f'"{k}"' for k in keys)
            res = execute_db(f'INSERT INTO "{table}" ({colsql}) VALUES ({ph}) RETURNING id',
                             tuple(fields[k] for k in keys))
            result = {"inserted_id": res.get("id") if res else None}
        elif act["action_type"] == "update":
            keys = list(fields.keys())
            setsql = ",".join(f'"{k}"=%s' for k in keys)
            execute_db(f'UPDATE "{table}" SET {setsql} WHERE id=%s',
                       tuple(fields[k] for k in keys) + (act["target_id"],))
            result = {"updated_id": act["target_id"]}
        elif act["action_type"] == "delete":
            execute_db(f'DELETE FROM "{table}" WHERE id=%s', (act["target_id"],))
            result = {"deleted_id": act["target_id"]}
        else:
            return {"error": "unknown action_type"}, 400
    except Exception as e:
        execute_db("UPDATE admin_pending_actions SET status='error', error_text=%s, "
                   "decided_at=NOW() WHERE id=%s", (str(e)[:300], action_id))
        return {"error": str(e)[:300]}, 500
    execute_db("UPDATE admin_pending_actions SET status='approved', result_json=%s::jsonb, "
               "decided_at=NOW() WHERE id=%s", (json.dumps(result), action_id))
    return {"success": True, "result": result}, 200


def reject_action(action_id):
    act = query_db("SELECT status FROM admin_pending_actions WHERE id=%s", (action_id,), fetchone=True)
    if not act:
        return {"error": "not found"}, 404
    if act["status"] != "pending":
        return {"error": f"already {act['status']}"}, 409
    execute_db("UPDATE admin_pending_actions SET status='rejected', decided_at=NOW() WHERE id=%s",
               (action_id,))
    return {"success": True}, 200


# ---- Tool schemas + dispatch -------------------------------------------
def _schema(name, desc, props=None, required=None):
    params = {"type": "object", "properties": props or {}}
    if required:
        params["required"] = required
    return {"type": "function", "function": {"name": name, "description": desc,
                                              "parameters": params}}


ADMIN_TOOLS = [
    _schema("admin_list_tables", "List all public tables. Call first to discover data."),
    _schema("admin_describe_table", "Columns + types + row count for one table. Call before "
            "proposing a write so column names are correct.",
            {"table_name": {"type": "string"}}, ["table_name"]),
    _schema("admin_run_sql", "Run a single READ-ONLY SELECT (max 100 rows). Writes are rejected — "
            "use admin_propose_* for changes.", {"sql": {"type": "string"}}, ["sql"]),
    _schema("admin_overview_stats", "Dashboard summary of recent activity counts."),
    _schema("admin_propose_insert", "Propose creating a row (awaits owner approval; nothing is "
            "written until approved). Allowed tables: " + ", ".join(sorted(ADMIN_WRITABLE_TABLES)),
            {"table_name": {"type": "string"}, "fields": {"type": "object", "additionalProperties": True}},
            ["table_name", "fields"]),
    _schema("admin_propose_update", "Propose changing one row by id (awaits approval).",
            {"table_name": {"type": "string"}, "row_id": {"type": "integer"},
             "fields": {"type": "object", "additionalProperties": True}},
            ["table_name", "row_id", "fields"]),
    _schema("admin_propose_delete", "Propose deleting one row by id (awaits approval).",
            {"table_name": {"type": "string"}, "row_id": {"type": "integer"}},
            ["table_name", "row_id"]),
]

_READ_EXECUTORS = {
    "admin_list_tables": admin_list_tables,
    "admin_describe_table": admin_describe_table,
    "admin_run_sql": admin_run_sql,
    "admin_overview_stats": admin_overview_stats,
}
_PROPOSE_EXECUTORS = {
    "admin_propose_insert": admin_propose_insert,
    "admin_propose_update": admin_propose_update,
    "admin_propose_delete": admin_propose_delete,
}


def execute_admin_tool(name, args_json, session_id=""):
    """Dispatch an admin tool call. Returns ``(result_json_str, log_entry)``."""
    try:
        args = json.loads(args_json) if isinstance(args_json, str) else (args_json or {})
        if not isinstance(args, dict):
            args = {}
    except Exception:
        args = {}
    entry = {"name": name, "args": args, "error": ""}
    try:
        if name in _READ_EXECUTORS:
            result = _READ_EXECUTORS[name](**args)
        elif name in _PROPOSE_EXECUTORS:
            result = _PROPOSE_EXECUTORS[name](_session_id=session_id, **args)
        else:
            result = {"error": f"unknown tool {name}"}
            entry["error"] = "unknown_tool"
    except TypeError as e:
        result = {"error": f"bad arguments: {e}"}
        entry["error"] = str(e)[:200]
    except Exception as e:
        result = {"error": str(e)[:300]}
        entry["error"] = str(e)[:200]
    return json.dumps(result, default=str), entry
