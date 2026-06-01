"""Task 053 — Datahub semantic layer (schema + manual CRUD). Embedded Postgres.

Verifies the new annotation tables exist (init_db + migration 0024), the
connections list includes the app's own DB as connection 0, and the super-admin
CRUD upserts/deletes table/column/relationship/example rows (a manual save marks
them reviewed=true). Client sessions are 403'd.
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


def _csrf():
    return {"X-CSRF-Token": "t"}


def _wipe():
    for t in ("db_table_annotations", "db_column_annotations",
              "db_relationships", "db_query_examples"):
        app.execute_db(f"DELETE FROM {t} WHERE connection_id=0")


# ---- connections list -------------------------------------------------------

def test_connections_include_app_db():
    c = _sa()
    r = c.get("/admin/api/datahub/connections")
    assert r.status_code == 200
    conns = r.get_json()["connections"]
    app_conn = [x for x in conns if x["id"] == 0]
    assert app_conn and app_conn[0]["builtin"] is True
    assert app_conn[0]["kind"] == "internal"


# ---- table annotation upsert ------------------------------------------------

def test_table_annotation_upsert_marks_reviewed():
    _wipe()
    c = _sa()
    try:
        r = c.put("/admin/api/datahub/0/table-annotation",
                  json={"table_name": "leads", "description": "Captured sales leads",
                        "is_sensitive": True}, headers=_csrf())
        assert r.status_code == 200
        row = app.query_db("SELECT description, is_sensitive, ai_generated, reviewed "
                           "FROM db_table_annotations WHERE connection_id=0 AND table_name='leads'",
                           fetchone=True)
        assert row["description"] == "Captured sales leads"
        assert row["is_sensitive"] is True
        assert row["ai_generated"] is False and row["reviewed"] is True
        # Upsert again (idempotent on the unique key).
        c.put("/admin/api/datahub/0/table-annotation",
              json={"table_name": "leads", "description": "Updated"}, headers=_csrf())
        n = app.query_db("SELECT COUNT(*) n FROM db_table_annotations "
                         "WHERE connection_id=0 AND table_name='leads'", fetchone=True)["n"]
        assert n == 1
    finally:
        _wipe()


def test_table_annotation_requires_name():
    c = _sa()
    r = c.put("/admin/api/datahub/0/table-annotation", json={}, headers=_csrf())
    assert r.status_code == 400


# ---- column annotation ------------------------------------------------------

def test_column_annotation_upsert():
    _wipe()
    c = _sa()
    try:
        r = c.put("/admin/api/datahub/0/column-annotation",
                  json={"table_name": "leads", "column_name": "email",
                        "description": "Lead email", "semantic_type": "email",
                        "is_sensitive": True, "sample_values": ["a@b.com", "c@d.com"]},
                  headers=_csrf())
        assert r.status_code == 200
        row = app.query_db("SELECT semantic_type, is_sensitive, sample_values, reviewed "
                           "FROM db_column_annotations WHERE connection_id=0 "
                           "AND table_name='leads' AND column_name='email'", fetchone=True)
        assert row["semantic_type"] == "email" and row["is_sensitive"] is True
        assert app._vp_as_list(row["sample_values"]) == ["a@b.com", "c@d.com"]
        assert row["reviewed"] is True
    finally:
        _wipe()


# ---- relationships + examples ----------------------------------------------

def test_relationship_and_example_and_get():
    _wipe()
    c = _sa()
    try:
        assert c.post("/admin/api/datahub/0/relationship",
                      json={"from_table": "orders", "from_column": "lead_id",
                            "to_table": "leads", "to_column": "id",
                            "description": "order belongs to lead"},
                      headers=_csrf()).status_code == 200
        assert c.post("/admin/api/datahub/0/example",
                      json={"question": "How many leads this week?",
                            "sql": "SELECT count(*) FROM leads"},
                      headers=_csrf()).status_code == 200
        ann = c.get("/admin/api/datahub/0/annotations").get_json()
        assert len(ann["relationships"]) == 1 and len(ann["examples"]) == 1
        rel_id = ann["relationships"][0]["id"]
        # Delete the relationship.
        assert c.delete(f"/admin/api/datahub/annotation/relationship/{rel_id}",
                        headers=_csrf()).status_code == 200
        ann2 = c.get("/admin/api/datahub/0/annotations").get_json()
        assert len(ann2["relationships"]) == 0
    finally:
        _wipe()


def test_delete_bad_kind_400():
    c = _sa()
    assert c.delete("/admin/api/datahub/annotation/nope/1",
                    headers=_csrf()).status_code == 400


# ---- gating -----------------------------------------------------------------

def test_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/datahub/connections").status_code == 403
    assert c.put("/admin/api/datahub/0/table-annotation",
                 json={"table_name": "x"}, headers={"X-CSRF-Token": "t"}).status_code == 403
