"""Task 036 — RAG document audience scoping. Embedded Postgres."""
import os
import app
import rag

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _seed_doc(audience="both"):
    row = app.execute_db(
        "INSERT INTO rag_documents (tenant_id, filename, status, audience) "
        "VALUES (1, %s, 'ready', %s) RETURNING id", ("doc.pdf", audience))
    return row["id"]


def test_audience_column_and_default():
    col = app.query_db(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name='rag_documents' AND column_name='audience'", fetchone=True)
    assert col is not None
    did = app.execute_db(
        "INSERT INTO rag_documents (tenant_id, filename, status) "
        "VALUES (1,'d2.pdf','ready') RETURNING id")["id"]
    got = app.query_db("SELECT audience FROM rag_documents WHERE id=%s", (did,), fetchone=True)
    assert got["audience"] == "both"  # default


def test_set_audience_helper_validates():
    did = _seed_doc("both")
    assert rag.set_audience(did, tenant_id=1, audience="visitor") is True
    assert app.query_db("SELECT audience FROM rag_documents WHERE id=%s", (did,), fetchone=True)["audience"] == "visitor"
    assert rag.set_audience(did, tenant_id=1, audience="garbage") is False  # invalid
    assert rag.set_audience(99999, tenant_id=1, audience="admin") is False  # wrong row


def test_audience_route_super_admin_vs_client():
    did = _seed_doc("both")
    sa = app.app.test_client(); sa.post("/admin/login", data={"password": ADMIN_PW})
    with sa.session_transaction() as s: s["_csrf_token"] = "t"
    r = sa.put(f"/admin/api/kb/{did}/audience", json={"audience": "admin"}, headers={"X-CSRF-Token": "t"})
    assert r.status_code == 200 and r.get_json()["audience"] == "admin"
    bad = sa.put(f"/admin/api/kb/{did}/audience", json={"audience": "nope"}, headers={"X-CSRF-Token": "t"})
    assert bad.status_code == 400
    missing = sa.put("/admin/api/kb/999999/audience", json={"audience": "both"}, headers={"X-CSRF-Token": "t"})
    assert missing.status_code == 404
    cl = app.app.test_client(); cl.post("/admin/login", data={"password": CLIENT_PW})
    with cl.session_transaction() as s: s["_csrf_token"] = "t"
    assert cl.put(f"/admin/api/kb/{did}/audience", json={"audience": "both"}, headers={"X-CSRF-Token": "t"}).status_code == 403


def test_list_documents_returns_audience():
    _seed_doc("visitor")
    docs = rag.list_documents(tenant_id=1)
    assert docs and all("audience" in d for d in docs)
