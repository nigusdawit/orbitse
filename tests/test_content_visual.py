"""Task 066 — Visual content scaffold. Embedded Postgres; LLM + image client
stubbed (no spend, no network).

Covers: content_assets schema, the gate + master switch, per-type generation
(diagram→Mermaid ready, clip→storyboard planned, image→placeholder planned by
default, image→openai_image ready when opted in), stitch scaffold, embed into a
draft body (image / diagram / planned), routes, and client-403.
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


# ---- fakes ------------------------------------------------------------------

class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = None


class _Completions:
    def create(self, **kw):
        sysmsg = next((m["content"] for m in kw.get("messages", [])
                       if m.get("role") == "system"), "")
        if "Mermaid" in sysmsg:
            return _Resp(json.dumps({"mermaid": "flowchart TD; A-->B", "title": "Flow"}))
        if "storyboard" in sysmsg:
            return _Resp(json.dumps({"scenes": [{"text": "s1", "visual": "v1"},
                                                {"text": "s2", "visual": "v2"}],
                                     "title": "Clip"}))
        return _Resp("{}")


class _Chat:
    completions = _Completions()


class _FakeOpenAI:
    chat = _Chat()

    def with_options(self, **kw):
        return self


class _ImgData:
    def __init__(self, url):
        self.url = url


class _ImgResp:
    def __init__(self, url):
        self.data = [_ImgData(url)]


class _Images:
    def generate(self, **kw):
        return _ImgResp("https://img.example/generated.png")


class _FakeDirect:
    images = _Images()


def _enable(monkeypatch):
    app.set_ai_setting("visual_content_enabled", True)
    app._invalidate_ai_control()
    monkeypatch.setattr(app, "openai_client", _FakeOpenAI())


def _reset():
    for k in ("visual_content_enabled", "image_model", "content_model",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM content_assets WHERE tenant_id=1")
    app.execute_db("DELETE FROM content_drafts WHERE tenant_id=1")


def _seed_draft():
    return app.execute_db(
        "INSERT INTO content_drafts (tenant_id, content_type, title, body, status) "
        "VALUES (1,'blog','My Post','Intro paragraph.','draft') RETURNING id")["id"]


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


# ---- schema -----------------------------------------------------------------

def test_assets_table_exists():
    app.query_db("SELECT COUNT(*) AS n FROM content_assets", fetchone=True)


# ---- gate -------------------------------------------------------------------

def test_visual_gated_off():
    _reset()
    assert "error" in app._rce_create_visual(asset_type="image", brief="x", draft_id=None,
                                              report_id=1)


def test_visual_master_switch(monkeypatch):
    app.set_ai_setting("visual_content_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    monkeypatch.setattr(app, "openai_client", _FakeOpenAI())
    try:
        assert "error" in app._rce_create_visual(asset_type="diagram", brief="x",
                                                  report_id=1)
    finally:
        _reset()


# ---- per-type generation ----------------------------------------------------

def test_diagram_ready_with_mermaid(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        a = app._rce_create_visual(draft_id=did, asset_type="diagram",
                                   brief="show the flow")
        assert a["asset_type"] == "diagram" and a["provider"] == "mermaid"
        assert a["status"] == "ready" and "flowchart" in a["spec"]["mermaid"]
    finally:
        _wipe(); _reset()


def test_clip_planned_storyboard(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        a = app._rce_create_visual(draft_id=did, asset_type="clip", brief="promo")
        assert a["asset_type"] == "clip" and a["provider"] == "storyboard"
        assert a["status"] == "planned" and len(a["spec"]["scenes"]) == 2
    finally:
        _wipe(); _reset()


def test_image_placeholder_default(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        a = app._rce_create_visual(draft_id=did, asset_type="image", brief="a hero image")
        assert a["asset_type"] == "image" and a["provider"] == "placeholder"
        assert a["status"] == "planned" and not a["url"]   # no spend, nothing rendered
    finally:
        _wipe(); _reset()


def test_image_openai_provider_opt_in(monkeypatch):
    _wipe(); _enable(monkeypatch)
    monkeypatch.setattr(app, "openai_direct_client", _FakeDirect())
    try:
        did = _seed_draft()
        a = app._rce_create_visual(draft_id=did, asset_type="image",
                                   brief="a hero image", provider="openai_image")
        assert a["provider"] == "openai_image" and a["status"] == "ready"
        assert a["url"] == "https://img.example/generated.png"
    finally:
        _wipe(); _reset()


def test_invalid_asset_type(monkeypatch):
    _enable(monkeypatch)
    try:
        assert "error" in app._rce_create_visual(asset_type="hologram", report_id=1)
    finally:
        _reset()


# ---- stitch (scaffold) ------------------------------------------------------

def test_stitch_creates_planned_clip(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        a1 = app._rce_create_visual(draft_id=did, asset_type="image", brief="img1")
        a2 = app._rce_create_visual(draft_id=did, asset_type="image", brief="img2")
        clip = app._rce_stitch_assets(did, [a1["id"], a2["id"]], title="Reel")
        assert clip["asset_type"] == "clip" and clip["provider"] == "stitch"
        assert clip["status"] == "planned"
        assert set(clip["spec"]["source_asset_ids"]) == {a1["id"], a2["id"]}
    finally:
        _wipe(); _reset()


# ---- embed ------------------------------------------------------------------

def test_embed_image_and_diagram(monkeypatch):
    _wipe(); _enable(monkeypatch)
    monkeypatch.setattr(app, "openai_direct_client", _FakeDirect())
    try:
        did = _seed_draft()
        img = app._rce_create_visual(draft_id=did, asset_type="image",
                                     brief="hero", provider="openai_image")
        dia = app._rce_create_visual(draft_id=did, asset_type="diagram", brief="flow")
        assert app._rce_embed_asset(did, img["id"]).get("ok")
        assert app._rce_embed_asset(did, dia["id"]).get("ok")
        body = app.query_db("SELECT body FROM content_drafts WHERE id=%s",
                            (did,), fetchone=True)["body"]
        assert "![hero](https://img.example/generated.png)" in body
        assert "```mermaid" in body and "flowchart" in body
    finally:
        _wipe(); _reset()


def test_embed_planned_uses_placeholder_comment(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        a = app._rce_create_visual(draft_id=did, asset_type="image", brief="pending")
        app._rce_embed_asset(did, a["id"])
        body = app.query_db("SELECT body FROM content_drafts WHERE id=%s",
                            (did,), fetchone=True)["body"]
        assert f"<!-- image asset #{a['id']} pending" in body
    finally:
        _wipe(); _reset()


# ---- routes -----------------------------------------------------------------

def test_visual_routes(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        did = _seed_draft()
        c = _sa()
        r = c.post("/admin/api/content/visual/generate",
                   json={"draft_id": did, "asset_type": "diagram", "brief": "flow"},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200
        aid = r.get_json()["id"]
        lst = c.get(f"/admin/api/content/assets?draft_id={did}").get_json()["assets"]
        assert any(x["id"] == aid for x in lst)
        emb = c.post("/admin/api/content/visual/embed",
                     json={"draft_id": did, "asset_id": aid},
                     headers={"X-CSRF-Token": "t"})
        assert emb.status_code == 200 and emb.get_json().get("ok")
        # missing fields → 400
        assert c.post("/admin/api/content/visual/generate", json={},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
        assert c.post("/admin/api/content/visual/embed", json={"draft_id": did},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe(); _reset()


def test_routes_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/content/assets").status_code == 403
    assert c.post("/admin/api/content/visual/generate",
                  json={"draft_id": 1, "asset_type": "image"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


def test_tool_registered():
    assert "generate_visual" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "generate_visual" in names
