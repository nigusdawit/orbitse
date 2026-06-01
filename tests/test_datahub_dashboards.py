"""Task 058 — AI builds persistent dashboards + save-chart-to-dashboard.
Embedded Postgres.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _wipe():
    app.execute_db("DELETE FROM dashboards WHERE name IN "
                   "('AI Sales','AI Charts','From Chat')")


def test_spec_to_static_widget():
    wt, sc = app._dh_spec_to_static_widget({"type": "line", "labels": ["a"], "values": [1]})
    assert wt == "line" and sc["data"]["labels"] == ["a"]
    wt, sc = app._dh_spec_to_static_widget({"type": "kpi", "value": 5, "label": "x"})
    assert wt == "kpi" and sc["data"]["value"] == 5
    wt, sc = app._dh_spec_to_static_widget({"type": "pie"})  # unknown -> bar
    assert wt == "bar"


def test_create_dashboard_tool():
    _wipe()
    try:
        out = app._admin_tool_create_dashboard(name="AI Sales", widgets=[
            {"name": "Revenue", "chart": {"type": "bar", "labels": ["Jan"], "values": [100]}},
            {"name": "Visitors", "widget_type": "kpi", "source_type": "builtin",
             "source_config": {"metric": "visitors"}},
        ])
        assert out.get("ok") is True and out.get("widgets") == 2
        did = out["dashboard_id"]
        ws = app.query_db("SELECT name, widget_type, source_type FROM dashboard_widgets "
                          "WHERE dashboard_id=%s ORDER BY sort_order", (did,))
        assert ws[0]["source_type"] == "static" and ws[0]["widget_type"] == "bar"
        assert ws[1]["source_type"] == "builtin"
    finally:
        _wipe()


def test_create_dashboard_requires_name():
    assert "error" in app._admin_tool_create_dashboard(name="")


def test_static_widget_runs_and_returns_data():
    _wipe()
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    try:
        out = app._admin_tool_create_dashboard(name="From Chat", widgets=[
            {"name": "W", "chart": {"type": "line", "labels": ["a", "b"], "values": [1, 2]}}])
        did = out["dashboard_id"]
        wid = app.query_db("SELECT id FROM dashboard_widgets WHERE dashboard_id=%s",
                           (did,), fetchone=True)["id"]
        r = c.post(f"/admin/api/dashboards/widgets/{wid}/run", headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["labels"] == ["a", "b"] and data["values"] == [1, 2]
    finally:
        _wipe()


def test_save_chart_route_creates_widget():
    _wipe()
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    try:
        r = c.post("/admin/api/datahub/save-chart",
                   json={"dashboard_name": "AI Charts",
                         "spec": {"type": "kpi", "title": "Leads", "value": 9, "label": "total"}},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200, r.get_data(as_text=True)
        did = r.get_json()["dashboard_id"]
        w = app.query_db("SELECT widget_type, source_type, source_config FROM dashboard_widgets "
                         "WHERE dashboard_id=%s", (did,), fetchone=True)
        assert w["source_type"] == "static" and w["widget_type"] == "kpi"
        # Saving again finds the SAME dashboard (no duplicate).
        c.post("/admin/api/datahub/save-chart",
               json={"dashboard_name": "AI Charts", "spec": {"type": "bar", "values": [1]}},
               headers={"X-CSRF-Token": "t"})
        n = app.query_db("SELECT COUNT(*) AS n FROM dashboards WHERE name='AI Charts'",
                         fetchone=True)["n"]
        assert n == 1
    finally:
        _wipe()


def test_save_chart_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.post("/admin/api/datahub/save-chart", json={"spec": {"type": "kpi"}},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


def test_tool_registered():
    assert "admin_create_dashboard" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_create_dashboard" in names
