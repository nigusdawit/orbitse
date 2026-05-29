"""
admin_ai_platform.custom_skills
==============================

Admin-defined chat tools that need no code: **SQL skills** (a named read-only
SELECT with bound params) and **HTTP/webhook skills** (call a REST endpoint with
the model's args). These become callable tools in the visitor chat alongside
the builtins.

Guards:
  * SQL skills run under the same SELECT-only / single-statement / 100-row /
    5s-timeout / rolled-back-txn rules as the admin SQL tool, with params bound
    via psycopg2 ``%(name)s`` (no string interpolation of values).
  * HTTP skills are SSRF-validated at call time — the resolved host must be a
    public address (no loopback/private/link-local/reserved), and only
    http/https schemes are allowed.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import re
from urllib.parse import urlparse

import httpx

from .db import get_db, query_db

_SQL_DANGEROUS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|"
    r"EXECUTE|CALL|MERGE|VACUUM|REINDEX|CLUSTER|REFRESH|LISTEN|NOTIFY|DO|SET)\b",
    re.IGNORECASE)
_ROW_CAP = 100
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")


def valid_skill_name(name):
    return bool(name and _NAME_RE.match(name))


# ---- SSRF guard ---------------------------------------------------------
def _host_is_public(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _url_is_safe(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    return _host_is_public(p.hostname)


# ---- Schema building (enabled custom skills -> OpenAI tool schemas) ------
def custom_tool_schemas():
    out = []
    try:
        for r in (query_db("SELECT name, description, args_schema_json FROM custom_sql_skills "
                           "WHERE enabled = TRUE") or []):
            out.append(_schema(r))
        for r in (query_db("SELECT name, description, args_schema_json FROM custom_webhook_skills "
                           "WHERE enabled = TRUE") or []):
            out.append(_schema(r))
    except Exception as e:
        print(f"[custom_skills] schema build failed: {e}")
    return out


def _schema(row):
    params = row.get("args_schema_json")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {"type": "object", "properties": {}}
    return {"type": "function", "function": {
        "name": row["name"], "description": row.get("description") or "",
        "parameters": params or {"type": "object", "properties": {}}}}


def is_custom_skill(name):
    try:
        return bool(query_db(
            "SELECT 1 FROM custom_sql_skills WHERE name=%s AND enabled=TRUE "
            "UNION SELECT 1 FROM custom_webhook_skills WHERE name=%s AND enabled=TRUE",
            (name, name), fetchone=True))
    except Exception:
        return False


# ---- Execution ----------------------------------------------------------
def execute_custom_skill(name, args):
    """Run a custom SQL or HTTP skill. Returns a JSON-serialisable result dict."""
    sql_row = query_db("SELECT * FROM custom_sql_skills WHERE name=%s AND enabled=TRUE",
                       (name,), fetchone=True)
    if sql_row:
        return _run_sql_skill(sql_row, args or {})
    web_row = query_db("SELECT * FROM custom_webhook_skills WHERE name=%s AND enabled=TRUE",
                       (name,), fetchone=True)
    if web_row:
        return _run_webhook_skill(web_row, args or {})
    return {"error": f"unknown custom skill {name}"}


def _run_sql_skill(row, args):
    sql = (row.get("sql_template") or "").strip().rstrip(";").strip()
    if not sql:
        return {"error": "empty sql_template"}
    if ";" in sql:
        return {"error": "only a single statement is allowed"}
    low = sql.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return {"error": "only SELECT / WITH ... SELECT is allowed"}
    if _SQL_DANGEROUS.search(sql):
        return {"error": "forbidden keyword in sql_template"}
    conn = get_db()
    try:
        conn.autocommit = False
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = 5000")
            cur.execute(sql, args)  # %(name)s params bound safely
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


def _run_webhook_skill(row, args):
    url = row.get("url") or ""
    if not _url_is_safe(url):
        return {"error": "url failed SSRF safety check (must be a public http/https host)"}
    method = (row.get("method") or "POST").upper()
    headers = row.get("headers_json") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except Exception:
            headers = {}
    timeout = int(row.get("timeout_seconds") or 10)
    try:
        if method == "GET":
            resp = httpx.get(url, params=args, headers=headers, timeout=timeout)
        else:
            resp = httpx.request(method, url, json=args, headers=headers, timeout=timeout)
        body = resp.text[:4000]
        try:
            parsed = resp.json()
        except Exception:
            parsed = None
        return {"status": resp.status_code, "json": parsed,
                "text": None if parsed is not None else body}
    except Exception as e:
        return {"error": f"request failed: {str(e)[:200]}"}
