"""Task 061 — multi-database connectors (MySQL + generic 'Any database URL').
Embedded Postgres. Live MySQL queries need a real MySQL (operator step); here we
verify the unified connection list, multi-kind create/test, dispatch routing,
read-only enforcement on the SQLAlchemy path, and the kind-aware resolver.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _wipe():
    app.execute_db("DELETE FROM external_data_connections WHERE name LIKE 'mdb-%'")


# ---- create route accepts the new kinds ------------------------------------

def test_create_accepts_mysql_and_sql_and_rejects_bad():
    _wipe()
    c = _sa()
    try:
        for kind, cfg in [("mysql", "mysql://u:p@h:3306/db"),
                          ("sql", "mssql+pyodbc://u:p@h/db"),
                          ("postgres", "postgres://u:p@h:5432/db")]:
            r = c.post("/admin/api/external-connections",
                       json={"name": f"mdb-{kind}", "kind": kind, "config": cfg},
                       headers={"X-CSRF-Token": "t"})
            assert r.status_code == 201, (kind, r.get_data(as_text=True))
        # Unknown kind rejected.
        assert c.post("/admin/api/external-connections",
                      json={"name": "mdb-x", "kind": "oracle-ish", "config": "x"},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
        # SQL kinds require a URL.
        assert c.post("/admin/api/external-connections",
                      json={"name": "mdb-empty", "kind": "mysql", "config": ""},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe()


# ---- unified list: a connection shows in BOTH surfaces ---------------------

def test_connection_unified_across_surfaces():
    _wipe()
    c = _sa()
    try:
        c.post("/admin/api/external-connections",
               json={"name": "mdb-shared", "kind": "mysql", "config": "mysql://u:p@h/db"},
               headers={"X-CSRF-Token": "t"})
        # Dashboards surface (external-connections list).
        ext = c.get("/admin/api/external-connections").get_json()
        assert any(x["name"] == "mdb-shared" and x["kind"] == "mysql" for x in ext)
        # Datahub surface (datahub/connections list) — same row appears.
        dh = c.get("/admin/api/datahub/connections").get_json()["connections"]
        assert any(x["name"] == "mdb-shared" and x["kind"] == "mysql" for x in dh)
        # The app DB is still listed as the built-in connection 0.
        assert any(x["id"] == 0 and x["builtin"] for x in dh)
    finally:
        _wipe()


# ---- dispatch routes by kind -----------------------------------------------

def test_run_external_db_dispatch(monkeypatch):
    calls = {}
    monkeypatch.setattr(app, "_run_external_postgres",
                        lambda *a, **k: calls.setdefault("pg", a))
    monkeypatch.setattr(app, "_run_external_sqlalchemy",
                        lambda kind, *a, **k: calls.setdefault("sa", kind))
    app._run_external_db("postgres", "postgres://x", "SELECT 1")
    app._run_external_db("mysql", "mysql://x", "SELECT 1")
    app._run_external_db("sql", "sqlite://", "SELECT 1")
    assert "pg" in calls and calls["sa"] in ("mysql", "sql")


# ---- read-only enforcement on the SQLAlchemy path (no DB needed) -----------

def test_sqlalchemy_runner_rejects_writes_before_connecting():
    for bad in ["DELETE FROM users", "UPDATE t SET x=1", "DROP TABLE t",
                "SELECT 1; DROP TABLE t"]:
        try:
            app._run_external_sqlalchemy("mysql", "mysql://u:p@h/db", bad)
            assert False, f"should have rejected: {bad}"
        except ValueError:
            pass  # rejected up front, never reached a connection


def test_sa_engine_normalizes_mysql_url():
    eng = app._sa_engine("mysql", "mysql://u:p@host:3306/db")
    try:
        assert eng.url.drivername == "mysql+pymysql"
    finally:
        eng.dispose()


# ---- kind-aware connection resolver ----------------------------------------

def test_dh_sql_connection_resolves_kind():
    _wipe()
    try:
        # App DB (connection 0) is postgres, no URL.
        kind, url, err = app._dh_sql_connection(0)
        assert kind == "postgres" and url is None and err is None
        # A MySQL external connection resolves with its decrypted URL.
        rid = app.execute_db(
            "INSERT INTO external_data_connections (name, kind, encrypted_config) "
            "VALUES ('mdb-my','mysql',%s) RETURNING id",
            (app.encrypt_secret("mysql://u:p@h/db"),))["id"]
        kind, url, err = app._dh_sql_connection(rid)
        assert kind == "mysql" and url == "mysql://u:p@h/db" and err is None
        # A REST connection is not queryable as SQL.
        rrid = app.execute_db(
            "INSERT INTO external_data_connections (name, kind, encrypted_config) "
            "VALUES ('mdb-rest','rest',%s) RETURNING id",
            (app.encrypt_secret('{"url":"https://x"}'),))["id"]
        _k, _u, err2 = app._dh_sql_connection(rrid)
        assert err2 and "REST" in err2
        # Unknown id errors.
        _k, _u, err3 = app._dh_sql_connection(999999)
        assert err3 and "not found" in err3.lower()
    finally:
        _wipe()


# ---- query_connection dispatches mysql to the SQLAlchemy path --------------

def test_query_connection_mysql_path(monkeypatch):
    _wipe()
    try:
        rid = app.execute_db(
            "INSERT INTO external_data_connections (name, kind, encrypted_config) "
            "VALUES ('mdb-q','mysql',%s) RETURNING id",
            (app.encrypt_secret("mysql://u:p@h/db"),))["id"]
        monkeypatch.setattr(app, "_run_external_sqlalchemy",
                            lambda *a, **k: {"columns": ["n"], "rows": [[7]]})
        out = app._admin_tool_query_connection(rid, sql="SELECT count(*) AS n FROM t")
        assert out.get("rows") == [[7]] and out.get("row_count") == 1
        # Writes still rejected before dispatch.
        assert "error" in app._admin_tool_query_connection(rid, sql="DELETE FROM t")
    finally:
        _wipe()


# ---- test endpoint handles mysql without 500 -------------------------------

def test_test_endpoint_mysql_graceful():
    _wipe()
    c = _sa()
    try:
        rid = app.execute_db(
            "INSERT INTO external_data_connections (name, kind, encrypted_config) "
            "VALUES ('mdb-test','mysql',%s) RETURNING id",
            (app.encrypt_secret("mysql://u:p@nonexistent-host-zzz:3306/db"),))["id"]
        r = c.post(f"/admin/api/external-connections/{rid}/test", headers={"X-CSRF-Token": "t"})
        # Unreachable host → success:false, but a clean 200 (no 500).
        assert r.status_code == 200
        assert r.get_json().get("success") is False
    finally:
        _wipe()
