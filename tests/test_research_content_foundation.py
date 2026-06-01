"""Task 062 — Research & Content Engine foundation. Embedded Postgres.

Verifies the new tables exist (init_db + migration 0026), the AI Control knobs
are registered + default-OFF + master-switch-inert, and the super-admin read
APIs return reports (with sources) + drafts and 403 a client.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def _wipe():
    for t in ("content_drafts", "research_sources", "research_reports",
              "publish_capabilities"):
        app.execute_db(f"DELETE FROM {t} WHERE tenant_id=1")


# ---- schema exists ----------------------------------------------------------

def test_tables_exist():
    for t in ("research_reports", "research_sources", "content_drafts",
              "publish_capabilities"):
        # A COUNT against each table proves the migration/init created it.
        app.query_db(f"SELECT COUNT(*) AS n FROM {t}", fetchone=True)


# ---- knobs registered, default off, master-switch-aware --------------------

def test_knobs_registered_and_default_off():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"research_hub_enabled", "content_studio_enabled",
            "visual_content_enabled", "autopublish_enabled",
            "research_max_sources", "research_model", "content_model",
            "image_model"} <= keys
    for k in ("research_hub_enabled", "content_studio_enabled",
              "visual_content_enabled", "autopublish_enabled"):
        assert app.get_ai_setting(k) is False


def test_master_switch_forces_off():
    app.set_ai_setting("research_hub_enabled", True)
    app.set_ai_setting("content_studio_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("research_hub_enabled") is False
        assert app.get_ai_setting("content_studio_enabled") is False
    finally:
        for k in ("research_hub_enabled", "content_studio_enabled",
                  "ai_enhancements_enabled"):
            app.reset_ai_setting(k)
        app._invalidate_ai_control()


# ---- read APIs --------------------------------------------------------------

def test_reports_api_with_sources():
    _wipe()
    c = _sa()
    try:
        rid = app.execute_db(
            "INSERT INTO research_reports (tenant_id, topic, summary, key_points, "
            "citations, status) VALUES (1,'Competitor pricing','A summary',"
            "'[\"point a\",\"point b\"]'::jsonb,'[{\"url\":\"https://x\"}]'::jsonb,'draft') "
            "RETURNING id")["id"]
        app.execute_db(
            "INSERT INTO research_sources (tenant_id, report_id, source_type, url, title) "
            "VALUES (1,%s,'web','https://x','Source X')", (rid,))
        lst = c.get("/admin/api/research/reports").get_json()["reports"]
        assert any(r["id"] == rid and r["topic"] == "Competitor pricing" for r in lst)
        one = c.get(f"/admin/api/research/reports/{rid}").get_json()
        assert one["key_points"] == ["point a", "point b"]
        assert one["citations"] and one["citations"][0]["url"] == "https://x"
        assert one["sources"] and one["sources"][0]["title"] == "Source X"
        assert c.get("/admin/api/research/reports/99999").status_code == 404
    finally:
        _wipe()


def test_drafts_api_filters():
    _wipe()
    c = _sa()
    try:
        app.execute_db("INSERT INTO content_drafts (tenant_id, content_type, title, status) "
                       "VALUES (1,'blog','Post A','draft'),(1,'social','Tweet B','approved')")
        alld = c.get("/admin/api/content/drafts").get_json()["drafts"]
        assert len(alld) >= 2
        only = c.get("/admin/api/content/drafts?status=approved&type=social").get_json()["drafts"]
        assert only and all(d["status"] == "approved" and d["content_type"] == "social" for d in only)
    finally:
        _wipe()


# ---- gating -----------------------------------------------------------------

def test_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    assert c.get("/admin/api/research/reports").status_code == 403
    assert c.get("/admin/api/content/drafts").status_code == 403
