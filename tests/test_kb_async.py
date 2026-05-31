"""Task 039 — async KB ingestion (gated). Embedded Postgres."""
import io, os, time
import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _sa():
    c = app.app.test_client(); c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s: s["_csrf_token"] = "t"
    return c


def _upload(c, name="doc.txt", body=b"hello world knowledge"):
    return c.post("/admin/api/kb/upload",
                  data={"file": (io.BytesIO(body), name)},
                  headers={"X-CSRF-Token": "t"},
                  content_type="multipart/form-data")


def test_inline_default_returns_200_with_doc():
    app.reset_ai_setting("async_ingestion_enabled"); app._invalidate_ai_control()
    before = app.query_db("SELECT COUNT(*) AS n FROM rag_documents", fetchone=True)["n"]
    r = _upload(_sa(), "inline.txt")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "document_id" in r.get_json()
    after = app.query_db("SELECT COUNT(*) AS n FROM rag_documents", fetchone=True)["n"]
    assert after == before + 1


def test_async_returns_202_and_thread_ingests():
    app.set_ai_setting("async_ingestion_enabled", True); app._invalidate_ai_control()
    try:
        before = app.query_db("SELECT COUNT(*) AS n FROM rag_documents", fetchone=True)["n"]
        r = _upload(_sa(), "async.txt")
        assert r.status_code == 202 and r.get_json().get("queued") is True
        # The background thread should insert the doc row shortly.
        ok = False
        for _ in range(40):  # up to ~4s
            n = app.query_db("SELECT COUNT(*) AS n FROM rag_documents", fetchone=True)["n"]
            if n == before + 1:
                ok = True; break
            time.sleep(0.1)
        assert ok, "async thread did not create the document row"
    finally:
        app.reset_ai_setting("async_ingestion_enabled"); app._invalidate_ai_control()


def test_master_off_forces_inline():
    # With the master kill switch off, async is forced inert → inline (200).
    app.set_ai_setting("async_ingestion_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        r = _upload(_sa(), "forced-inline.txt")
        assert r.status_code == 200  # inline, not 202
    finally:
        app.reset_ai_setting("async_ingestion_enabled")
        app.reset_ai_setting("ai_enhancements_enabled")
        app._invalidate_ai_control()
