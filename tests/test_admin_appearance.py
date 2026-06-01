"""Task 072 — super-admin admin-panel Appearance customizer. Embedded Postgres.

Verifies migration 0029 columns, the defensive reader, the super-admin save
endpoint (clamps numerics + validates colors/mode), client-403, and that the
dashboard route injects the theme variables for no-flash load.
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


def test_columns_exist():
    # A SELECT of the new columns proves migration 0029 ran (no error).
    app.query_db("SELECT admin_theme_mode, admin_theme_accent, admin_theme_accent2, "
                 "admin_theme_blur, admin_theme_radius, admin_theme_glass, "
                 "admin_theme_glow FROM site_settings WHERE id=1", fetchone=True)


def test_appearance_defaults():
    d = app._admin_appearance()
    assert d["mode"] in ("dark", "light")
    assert d["accent"].startswith("#")
    assert 0.0 <= d["glow"] <= 1.0


def test_save_clamp_and_persist():
    c = _sa()
    app.execute_db("INSERT INTO site_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    r = c.put("/admin/api/admin-appearance",
              json={"mode": "light", "accent": "#112233", "accent2": "#445566",
                    "blur": 999, "radius": -5, "glass": 2, "glow": -1},
              headers={"X-CSRF-Token": "t"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["mode"] == "light" and j["accent"] == "#112233" and j["accent2"] == "#445566"
    assert j["blur"] == 40 and j["radius"] == 0 and j["glass"] == 0.95 and j["glow"] == 0.0
    # persisted + read back through the defensive reader
    d = app._admin_appearance()
    assert d["mode"] == "light" and d["accent"] == "#112233" and d["blur"] == 40
    # bad mode + bad hex fall back to safe defaults
    j2 = c.put("/admin/api/admin-appearance", json={"mode": "weird", "accent": "notahex"},
               headers={"X-CSRF-Token": "t"}).get_json()
    assert j2["mode"] == "dark" and j2["accent"] == "#6c8cff"
    # restore defaults so other tests/UI aren't left in a weird state
    c.put("/admin/api/admin-appearance",
          json={"mode": "dark", "accent": "#6c8cff", "accent2": "#9a7cff",
                "blur": 18, "radius": 16, "glass": 0.55, "glow": 0.5},
          headers={"X-CSRF-Token": "t"})


def test_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.put("/admin/api/admin-appearance", json={"mode": "light"},
                 headers={"X-CSRF-Token": "t"}).status_code == 403


def test_dashboard_injects_theme():
    c = _sa()
    html = c.get("/admin").get_data(as_text=True)
    assert "data-admin-theme=" in html
    assert "admin-glass-theme" in html        # the glass CSS layer is present
    assert "--admin-accent" in html           # customizable vars injected
    assert 'id="tab-appearance"' in html      # the customizer tab rendered
