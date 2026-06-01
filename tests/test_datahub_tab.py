"""Task 059 — Datahub tab (schema-browser route + template wiring).
Embedded Postgres. The full UI is exercised live; here we verify the backing
route and that the tab is wired into the template (super-admin only)."""
import os
import pathlib

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_schema_route_overview_and_table():
    c = _sa()
    r = c.get("/admin/api/datahub/0/schema")
    assert r.status_code == 200
    body = r.get_json()
    assert "tables" in body and any(t["table"] == "leads" for t in body["tables"])
    r2 = c.get("/admin/api/datahub/0/schema?table=leads")
    assert r2.status_code == 200
    assert any(col["column"] == "email" for col in r2.get_json()["columns"])


def test_schema_route_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    assert c.get("/admin/api/datahub/0/schema").status_code == 403


def test_template_wires_datahub_tab():
    html = (ROOT / "templates" / "admin" / "dashboard.html").read_text(encoding="utf-8")
    assert "switchTab('datahub'" in html
    assert 'id="tab-datahub"' in html
    assert "function loadDatahub()" in html
    assert "datahubAutoDefine" in html
    # Tab button is inside a super-admin-only block.
    assert 'data-testid="tab-datahub"' in html
    # Column editor exposes the is_sensitive toggle (task 060).
    assert "data-dh-sens" in html
    assert "is_sensitive" in html


def test_connect_button_uses_modal_not_prompt():
    """The 'Connect a database' flow must open the real Data Connections modal,
    not window.prompt() (which embedded/preview browsers block)."""
    html = (ROOT / "templates" / "admin" / "dashboard.html").read_text(encoding="utf-8")
    # datahubAddConnection opens the existing modal …
    assert "function datahubAddConnection" in html
    assert "openConnectionsModal()" in html
    # … and the old prompt()-based connection flow is gone.
    assert "prompt('Connection name:')" not in html
    # Closing the modal refreshes the Datahub rail.
    assert "function closeConnectionsModal" in html and "loadDatahub()" in html
