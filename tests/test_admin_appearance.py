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
    # The glass CSS layer moved from an inline <style> into public/admin/theme.css
    # (task 076 de-monolith); assert it's linked into the page rather than inlined.
    assert "/admin/theme.css" in html         # the glass CSS layer is present (external)
    assert "--admin-accent" in html           # customizable vars injected
    assert 'id="tab-appearance"' in html      # the customizer tab rendered
    # task 073 — expanded controls injected as <html> data-* attrs (no-flash).
    assert "data-admin-density=" in html
    assert "data-admin-surface=" in html
    assert "data-admin-sidebar=" in html


# ---------------------------------------------------------------------------
# Task 073 — expanded Appearance controls (migration 0030): density, font
# scale/family, surface style, sidebar style, high-contrast, reduce-motion.
# ---------------------------------------------------------------------------

def test_ext_columns_exist():
    # A SELECT of the new columns proves migration 0030 ran (no error).
    app.query_db("SELECT admin_theme_density, admin_theme_font_scale, "
                 "admin_theme_font_family, admin_theme_surface, admin_theme_sidebar, "
                 "admin_theme_high_contrast, admin_theme_reduce_motion "
                 "FROM site_settings WHERE id=1", fetchone=True)


def test_ext_defaults():
    d = app._admin_appearance()
    assert d["density"] == "comfortable"
    assert d["font_scale"] == "md"
    assert d["font_family"] == "sans"
    assert d["surface"] == "glass"
    assert d["sidebar"] == "comfortable"
    assert d["high_contrast"] is False and d["reduce_motion"] is False


def test_ext_save_validate_and_persist():
    c = _sa()
    app.execute_db("INSERT INTO site_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # Valid values persist and are echoed back.
    r = c.put("/admin/api/admin-appearance",
              json={"mode": "dark", "density": "spacious", "font_scale": "lg",
                    "font_family": "inter", "surface": "minimal", "sidebar": "icons",
                    "high_contrast": True, "reduce_motion": True},
              headers={"X-CSRF-Token": "t"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["density"] == "spacious" and j["surface"] == "minimal" and j["sidebar"] == "icons"
    assert j["font_scale"] == "lg" and j["font_family"] == "inter"
    assert j["high_contrast"] is True and j["reduce_motion"] is True
    # Persisted + read back through the defensive reader.
    d = app._admin_appearance()
    assert d["density"] == "spacious" and d["font_family"] == "inter"
    assert d["surface"] == "minimal" and d["high_contrast"] is True
    # Invalid enum values fall back to safe defaults (not stored verbatim).
    j2 = c.put("/admin/api/admin-appearance",
               json={"density": "huge", "surface": "hologram", "font_scale": "xl",
                     "sidebar": "floating", "font_family": "comic-sans"},
               headers={"X-CSRF-Token": "t"}).get_json()
    assert j2["density"] == "comfortable" and j2["surface"] == "glass"
    assert j2["font_scale"] == "md" and j2["sidebar"] == "comfortable"
    assert j2["font_family"] == "sans"
    # Restore defaults so other tests / the live UI aren't left in a weird state.
    c.put("/admin/api/admin-appearance",
          json={"density": "comfortable", "font_scale": "md", "font_family": "sans",
                "surface": "glass", "sidebar": "comfortable",
                "high_contrast": False, "reduce_motion": False},
          headers={"X-CSRF-Token": "t"})


# ---------------------------------------------------------------------------
# Task 089 — "a lot more" Appearance controls (migration 0033): semantic/extra
# colours, typography, shape & depth, layout & motion, per-theme base colours,
# and save-your-own presets — all in the single admin_theme_extra JSONB blob.
# ---------------------------------------------------------------------------

def _reset_extra(c):
    """Clear all expanded knobs back to defaults (a PUT with no extra keys writes
    an empty blob) so later tests / the live UI start clean."""
    c.put("/admin/api/admin-appearance",
          json={"mode": "dark", "accent": "#6c8cff", "accent2": "#9a7cff",
                "blur": 18, "radius": 16, "glass": 0.55, "glow": 0.5,
                "density": "comfortable", "font_scale": "md", "font_family": "sans",
                "surface": "glass", "sidebar": "comfortable",
                "high_contrast": False, "reduce_motion": False},
          headers={"X-CSRF-Token": "t"})


def test_extra_column_exists():
    # A SELECT of the new column proves migration 0033 ran (no error).
    app.query_db("SELECT admin_theme_extra FROM site_settings WHERE id=1", fetchone=True)


def test_extra_defaults():
    d = app._admin_appearance()
    # Theme-agnostic colour + enum + numeric defaults == today's look.
    assert d["color_success"] == "#22c55e"
    assert d["color_warning"] == "#f59e0b"
    assert d["color_danger"] == "#ef4444"
    assert d["head_font"] == "serif"
    assert d["font_weight"] == "normal"
    assert d["shadow"] == "medium"
    assert d["focus_style"] == "ring"
    assert d["content_width"] == "full"
    assert d["header_style"] == "sticky"
    assert d["button_style"] == "solid"
    assert d["motion_speed"] == "normal"
    assert d["line_height"] == 1.3
    assert d["border_width"] == 1.0
    # Per-theme base colours flattened to <key>_dark/<key>_light for the pickers.
    assert d["bg_dark"] == "#0b1220" and d["bg_light"] == "#eef2fb"
    assert d["text_dark"] == "#e8edf6" and d["text_light"] == "#19233a"
    # Nothing customized out of the box.
    assert d["base_overrides"] == {}
    assert d["custom_presets"] == []


def test_extra_save_validate_persist():
    c = _sa()
    app.execute_db("INSERT INTO site_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # Valid expanded values persist + echo back.
    r = c.put("/admin/api/admin-appearance",
              json={"mode": "dark", "color_success": "#aabbcc", "shadow": "strong",
                    "head_font": "mono", "button_style": "outline", "line_height": 1.7,
                    "border_width": 2, "bg_dark": "#123456"},
              headers={"X-CSRF-Token": "t"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["color_success"] == "#aabbcc" and j["shadow"] == "strong"
    assert j["head_font"] == "mono" and j["button_style"] == "outline"
    assert j["line_height"] == 1.7 and j["border_width"] == 2.0
    assert j["bg_dark"] == "#123456"
    # bg_dark differs from default -> it's an override; bg_light untouched -> not.
    assert j["base_overrides"].get("bg_dark") == "#123456"
    assert "bg_light" not in j["base_overrides"]
    # Persisted + read back through the defensive reader.
    d = app._admin_appearance()
    assert d["color_success"] == "#aabbcc" and d["shadow"] == "strong"
    assert d["bg_dark"] == "#123456" and d["base_overrides"].get("bg_dark") == "#123456"
    # Invalid values fall back to safe defaults (never stored verbatim).
    j2 = c.put("/admin/api/admin-appearance",
               json={"color_success": "notahex", "shadow": "ginormous",
                     "head_font": "comic", "button_style": "neon", "bg_dark": "xyz"},
               headers={"X-CSRF-Token": "t"}).get_json()
    assert j2["color_success"] == "#22c55e" and j2["shadow"] == "medium"
    assert j2["head_font"] == "serif" and j2["button_style"] == "solid"
    assert j2["bg_dark"] == "#0b1220" and j2["base_overrides"] == {}
    _reset_extra(c)


def test_extra_numeric_clamp():
    c = _sa()
    j = c.put("/admin/api/admin-appearance",
              json={"line_height": 99, "border_width": 99, "letter_spacing": 99},
              headers={"X-CSRF-Token": "t"}).get_json()
    assert j["line_height"] == 1.9 and j["border_width"] == 3.0 and j["letter_spacing"] == 0.08
    j = c.put("/admin/api/admin-appearance",
              json={"line_height": -99, "border_width": -99, "letter_spacing": -99},
              headers={"X-CSRF-Token": "t"}).get_json()
    assert j["line_height"] == 1.2 and j["border_width"] == 0.0 and j["letter_spacing"] == -0.02
    _reset_extra(c)


def test_custom_presets_roundtrip_cap_sanitize():
    c = _sa()
    # junk first (so it's within the cap), then a label-less one (dropped), then
    # 30 valid presets (pushes the total past the cap of 24).
    presets = [
        {"id": "junk", "label": "Junk",
         "settings": {"evil": "x", "nested": {"a": 1}, "accent": "#abcdef"}},
        {"id": "nolabel", "label": "", "settings": {}},
    ]
    presets += [{"id": "p%d" % i, "label": "P%d" % i, "settings": {"shadow": "soft"}}
                for i in range(30)]
    j = c.put("/admin/api/admin-appearance",
              json={"custom_presets": presets}, headers={"X-CSRF-Token": "t"}).get_json()
    saved = j["custom_presets"]
    assert len(saved) <= 24                              # capped
    assert all(p["id"] and p["label"] for p in saved)    # id + label required
    assert not any(p["id"] == "nolabel" for p in saved)  # label-less dropped
    # Settings sanitized: known key kept, unknown + nested dropped.
    junk = [p for p in saved if p["id"] == "junk"]
    assert junk, "the in-cap junk preset should survive"
    s = junk[0]["settings"]
    assert "evil" not in s and "nested" not in s and s.get("accent") == "#abcdef"
    # Persisted.
    d = app._admin_appearance()
    assert len(d["custom_presets"]) == len(saved)
    _reset_extra(c)


def test_custom_preset_id_sanitized_against_xss():
    # SECURITY regression (task 089 review): a custom-preset id is reflected into
    # client-side markup, so a crafted id carrying HTML/JS must be stripped to
    # [a-z0-9] on BOTH save and read — never stored or echoed verbatim.
    c = _sa()
    evil = {"id": "x'><img src=x onerror=alert(1)>", "label": "Evil",
            "settings": {"accent": "#abcdef"}}
    j = c.put("/admin/api/admin-appearance",
              json={"custom_presets": [evil]}, headers={"X-CSRF-Token": "t"}).get_json()
    saved = j["custom_presets"]
    assert len(saved) == 1
    pid = saved[0]["id"]
    assert pid and all(ch.islower() or ch.isdigit() for ch in pid)   # [a-z0-9] only
    for bad in ("<", ">", "'", '"', " ", "(", ")", "="):
        assert bad not in pid
    # the read path sanitizes too (so a pre-existing bad row can't reach the DOM)
    rid = app._admin_appearance()["custom_presets"][0]["id"]
    assert "<" not in rid and "'" not in rid and ">" not in rid
    _reset_extra(c)


def test_fail_open_garbage_blob():
    # A corrupt (non-dict) blob must NEVER break the reader — it falls back to
    # all defaults instead of raising.
    app.execute_db("UPDATE site_settings SET admin_theme_extra=%s::jsonb WHERE id=1",
                   ('"corrupt-not-an-object"',))
    d = app._admin_appearance()
    assert d["color_success"] == "#22c55e"
    assert d["bg_dark"] == "#0b1220"
    assert d["base_overrides"] == {} and d["custom_presets"] == []
    # Reset to a clean empty object.
    app.execute_db("UPDATE site_settings SET admin_theme_extra='{}'::jsonb WHERE id=1")


# ---------------------------------------------------------------------------
# Task 090 — navigation governance (Classic vs Workspaces shell). Two behaviour
# knobs in admin_theme_extra, super-admin-set: nav_default + nav_allow_override.
# ---------------------------------------------------------------------------

def test_nav_settings_defaults():
    # Defaults must be classic + override-allowed. nav_allow_override is the
    # bool-default case that must read True even though the blob omits defaults.
    _reset_extra(_sa())  # isolate from any prior test that may have set these
    d = app._admin_appearance()
    assert d["nav_default"] == "classic"
    assert d["nav_allow_override"] is True


def test_nav_settings_save_validate():
    c = _sa()
    app.execute_db("INSERT INTO site_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # Super-admin sets org default = workspaces and locks normal-admin switching.
    j = c.put("/admin/api/admin-appearance",
              json={"nav_default": "workspaces", "nav_allow_override": False},
              headers={"X-CSRF-Token": "t"}).get_json()
    assert j["nav_default"] == "workspaces" and j["nav_allow_override"] is False
    d = app._admin_appearance()
    assert d["nav_default"] == "workspaces" and d["nav_allow_override"] is False
    # Invalid enum falls back to the safe default; bool re-enabled and persists.
    j2 = c.put("/admin/api/admin-appearance",
               json={"nav_default": "fancy", "nav_allow_override": True},
               headers={"X-CSRF-Token": "t"}).get_json()
    assert j2["nav_default"] == "classic" and j2["nav_allow_override"] is True
    _reset_extra(c)
