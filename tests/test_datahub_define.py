"""Task 055 — Datahub AI auto-define. Embedded Postgres, stubbed LLM (no spend).

Verifies the assistant drafts the semantic layer (ai_generated=true,
reviewed=false), never overwrites a reviewed row, masks secret-named sample
columns BEFORE they reach the model, and that the route is super-admin gated.
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")

DRAFT = {
    "tables": [{"table": "leads", "description": "Sales leads", "is_sensitive": True}],
    "columns": [{"table": "leads", "column": "email", "description": "Lead email",
                 "semantic_type": "email", "is_sensitive": True}],
    "relationships": [{"from_table": "leads", "from_column": "id",
                       "to_table": "callback_requests", "to_column": "id",
                       "description": "linked"}],
    "examples": [{"question": "How many leads?", "sql": "SELECT count(*) FROM leads"}],
}


class _Resp:
    def __init__(self, content):
        self.choices = [type("M", (), {"message": type("X", (), {"content": content})})]
        self.usage = None


class _CaptureOpenAI:
    def __init__(self, content):
        self._content = content
        self.captured = {}
        outer = self

        class _Comp:
            def create(self, **kw):
                outer.captured = kw
                return _Resp(content)
        self.chat = type("C", (), {"completions": _Comp()})()

    def with_options(self, **kw):
        return self


def _wipe():
    for t in ("db_table_annotations", "db_column_annotations",
              "db_relationships", "db_query_examples"):
        app.execute_db(f"DELETE FROM {t} WHERE connection_id=0")


def test_define_writes_ai_drafts():
    _wipe()
    saved = app.openai_client
    app.openai_client = _CaptureOpenAI(json.dumps(DRAFT))
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" not in out, out
        t = app.query_db("SELECT description, ai_generated, reviewed FROM db_table_annotations "
                         "WHERE connection_id=0 AND table_name='leads'", fetchone=True)
        assert t["description"] == "Sales leads"
        assert t["ai_generated"] is True and t["reviewed"] is False
        c = app.query_db("SELECT semantic_type, ai_generated FROM db_column_annotations "
                         "WHERE connection_id=0 AND table_name='leads' AND column_name='email'",
                         fetchone=True)
        assert c["semantic_type"] == "email" and c["ai_generated"] is True
        assert app.query_db("SELECT 1 FROM db_query_examples WHERE connection_id=0",
                            fetchone=True)
    finally:
        app.openai_client = saved
        _wipe()


def test_define_preserves_reviewed_rows():
    _wipe()
    # A human has reviewed the 'leads' table description.
    app.execute_db(
        "INSERT INTO db_table_annotations (connection_id, table_name, description, "
        "ai_generated, reviewed) VALUES (0,'leads','HUMAN OWNED',FALSE,TRUE)")
    saved = app.openai_client
    app.openai_client = _CaptureOpenAI(json.dumps(DRAFT))
    try:
        app._dh_ai_define(0, table="leads")
        t = app.query_db("SELECT description, reviewed FROM db_table_annotations "
                         "WHERE connection_id=0 AND table_name='leads'", fetchone=True)
        assert t["description"] == "HUMAN OWNED" and t["reviewed"] is True  # untouched
    finally:
        app.openai_client = saved
        _wipe()


def test_samples_redacted_before_llm():
    _wipe()
    app.execute_db("DROP TABLE IF EXISTS dh_secrets")
    app.execute_db("CREATE TABLE dh_secrets (id serial primary key, password text)")
    app.execute_db("INSERT INTO dh_secrets (password) VALUES ('topsecret-value')")
    saved = app.openai_client
    fake = _CaptureOpenAI(json.dumps({"tables": [], "columns": [],
                                      "relationships": [], "examples": []}))
    app.openai_client = fake
    try:
        app._dh_ai_define(0, table="dh_secrets")
        sent = json.dumps(fake.captured.get("messages", []))
        assert "topsecret-value" not in sent          # the secret never reached the model
        assert app._REDACTED_PLACEHOLDER in sent       # it was masked in the samples
    finally:
        app.openai_client = saved
        app.execute_db("DROP TABLE IF EXISTS dh_secrets")
        _wipe()


def test_define_no_openai_returns_error():
    saved = app.openai_client
    app.openai_client = None
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" in out
    finally:
        app.openai_client = saved


def test_define_route_gating():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    saved = app.openai_client
    app.openai_client = _CaptureOpenAI(json.dumps({"tables": [], "columns": [],
                                                   "relationships": [], "examples": []}))
    try:
        r = c.post("/admin/api/datahub/0/ai-define", json={"table": "leads"},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        app.openai_client = saved
        _wipe()
    if CLIENT_PW:
        cc = app.app.test_client()
        cc.post("/admin/login", data={"password": CLIENT_PW})
        with cc.session_transaction() as s:
            s["_csrf_token"] = "t"
        assert cc.post("/admin/api/datahub/0/ai-define", json={},
                       headers={"X-CSRF-Token": "t"}).status_code == 403


def test_tool_registered():
    assert "admin_define_schema" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_define_schema" in names
