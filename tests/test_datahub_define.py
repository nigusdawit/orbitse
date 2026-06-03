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


# ---------------------------------------------------------------------------
# Task 083 — selective/granular define + truncation fix. New stub records EVERY
# call's kwargs (the per-table loop makes multiple calls) and can serve a
# different body per call (so we can simulate one table truncating/failing).
# ---------------------------------------------------------------------------

class _SeqOpenAI:
    """OpenAI stub for the looped define. `bodies` is either a single string
    (served for every call) or a list served positionally (the last entry
    repeats if there are more calls than entries). Records each call's kwargs in
    .calls so tests can assert max_tokens / how many calls happened / which
    table each prompt focused on."""
    def __init__(self, bodies):
        self._bodies = bodies
        self.calls = []
        outer = self

        class _Comp:
            def create(self, **kw):
                idx = len(outer.calls)
                outer.calls.append(kw)
                if isinstance(outer._bodies, (list, tuple)):
                    b = outer._bodies[min(idx, len(outer._bodies) - 1)]
                else:
                    b = outer._bodies
                return _Resp(b)
        self.chat = type("C", (), {"completions": _Comp()})()

    def with_options(self, **kw):
        return self

    @property
    def captured(self):
        return self.calls[-1] if self.calls else {}


def _user_text(kw):
    """The user-message string from a recorded create() call."""
    for m in kw.get("messages", []):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def _system_text(kw):
    for m in kw.get("messages", []):
        if m.get("role") == "system":
            return m.get("content") or ""
    return ""


def test_define_max_tokens_raised():
    """The per-table draft must request a far larger budget than the old 2000 —
    at least the 8000 default knob — so a wide table isn't truncated."""
    _wipe()
    saved = app.openai_client
    fake = _SeqOpenAI(json.dumps(DRAFT))
    app.openai_client = fake
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" not in out, out
        assert fake.calls, "no LLM call captured"
        assert int(fake.calls[0].get("max_tokens") or 0) >= 8000, fake.calls[0].get("max_tokens")
    finally:
        app.openai_client = saved
        _wipe()


def test_define_single_column_only_that_column():
    """Per-column define writes only the targeted column, tells the model to
    describe ONLY it, and runs no relationships pass (single call)."""
    _wipe()
    col_blob = {"tables": [], "columns": [
        {"table": "leads", "column": "email", "description": "Lead email",
         "semantic_type": "email", "is_sensitive": True}],
        "relationships": [], "examples": []}
    saved = app.openai_client
    fake = _SeqOpenAI(json.dumps(col_blob))
    app.openai_client = fake
    try:
        out = app._dh_ai_define(0, table="leads", column="email")
        assert "error" not in out, out
        assert out.get("column") == "email"
        # Exactly one call (no separate relationships pass for a single column).
        assert len(fake.calls) == 1, len(fake.calls)
        assert "email" in _system_text(fake.calls[0])  # prompt focused on the column
        # Only the email column was written.
        rows = app.query_db("SELECT column_name FROM db_column_annotations "
                            "WHERE connection_id=0 AND table_name='leads'")
        assert [r["column_name"] for r in rows] == ["email"], rows
    finally:
        app.openai_client = saved
        _wipe()


def test_define_single_column_unknown_returns_error():
    _wipe()
    saved = app.openai_client
    app.openai_client = _SeqOpenAI(json.dumps(DRAFT))
    try:
        out = app._dh_ai_define(0, table="leads", column="does_not_exist")
        assert "error" in out and "does_not_exist" in out["error"], out
    finally:
        app.openai_client = saved
        _wipe()


def test_define_multi_table_loops_one_call_each():
    """A `tables` list loops the one-table primitive (one draft call per table)
    plus ONE relationships pass, and merges the per-table counts."""
    _wipe()
    per_table = json.dumps({
        "tables": [{"table": "leads", "description": "x", "is_sensitive": False}],
        "columns": [], "relationships": [], "examples": []})
    rel = json.dumps({"tables": [], "columns": [], "relationships": [],
                      "examples": [{"question": "q", "sql": "SELECT 1"}]})
    saved = app.openai_client
    # leads, callback_requests are both real app tables. 2 draft calls + 1 rel.
    fake = _SeqOpenAI([per_table, per_table, rel])
    app.openai_client = fake
    try:
        out = app._dh_ai_define(0, tables=["leads", "callback_requests"])
        assert "error" not in out, out
        assert out["tables_scanned"] == 2, out
        # 2 per-table draft calls + 1 relationships pass = 3 LLM calls.
        assert len(fake.calls) == 3, [(_user_text(c)[:40]) for c in fake.calls]
        # The relationships pass carries names+types only — NO sample rows.
        rel_call = fake.calls[-1]
        assert "samples" not in _user_text(rel_call)
    finally:
        app.openai_client = saved
        _wipe()


def test_define_partial_failure_not_silent():
    """One table returning an unparseable (truncated) body must NOT abort the
    batch: the good table is written and a `warnings` list surfaces the failure.
    A single-table failure returns an explicit error instead."""
    _wipe()
    good = json.dumps({
        "tables": [{"table": "leads", "description": "ok", "is_sensitive": False}],
        "columns": [], "relationships": [], "examples": []})
    truncated = '{"tables": [{"table": "leads", "descrip'  # cut off -> json.loads fails
    saved = app.openai_client
    # first table OK, second table truncated; rel pass (third) returns empty-ish.
    fake = _SeqOpenAI([good, truncated, json.dumps(
        {"relationships": [], "examples": []})])
    app.openai_client = fake
    try:
        out = app._dh_ai_define(0, tables=["leads", "callback_requests"])
        assert "error" not in out, out
        assert out.get("warnings"), out
        assert "callback_requests" in out["warnings"][0]
        assert out["tables_scanned"] == 1  # only the good one counted
    finally:
        app.openai_client = saved
        _wipe()
    # All tables failing -> a single clear error (the incomplete-response message).
    _wipe()
    app.openai_client = _SeqOpenAI('{"oops": ')  # every call unparseable
    try:
        out = app._dh_ai_define(0, tables=["leads", "callback_requests"])
        assert "error" in out and "incomplete" in out["error"].lower(), out
    finally:
        app.openai_client = saved
        _wipe()
    # A single table that fails -> explicit error (not warnings).
    _wipe()
    app.openai_client = _SeqOpenAI('{"bad": ')
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" in out, out
    finally:
        app.openai_client = saved
        _wipe()


def test_define_includes_views():
    """A VIEW is discovered (type=='view') and definable like a table."""
    _wipe()
    app.execute_db("DROP VIEW IF EXISTS dh_test_view")
    app.execute_db("CREATE VIEW dh_test_view AS SELECT 1 AS n")
    saved = app.openai_client
    view_blob = json.dumps({
        "tables": [{"table": "dh_test_view", "description": "a view", "is_sensitive": False}],
        "columns": [{"table": "dh_test_view", "column": "n", "description": "num",
                     "semantic_type": "id", "is_sensitive": False}],
        "relationships": [], "examples": []})
    app.openai_client = _SeqOpenAI(view_blob)
    try:
        kind, url, err = app._dh_sql_connection(0)
        objs = app._dh_intro_objects(0, kind, url)
        assert {o["name"]: o["type"] for o in objs}.get("dh_test_view") == "view"
        out = app._dh_ai_define(0, table="dh_test_view")
        assert "error" not in out, out
        t = app.query_db("SELECT description FROM db_table_annotations "
                         "WHERE connection_id=0 AND table_name='dh_test_view'",
                         fetchone=True)
        assert t and t["description"] == "a view"
    finally:
        app.openai_client = saved
        app.execute_db("DROP VIEW IF EXISTS dh_test_view")
        _wipe()


def test_define_route_accepts_tables_and_column():
    """The route forwards {tables:[...]} (batch) and {table,column} (one column)."""
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    saved = app.openai_client
    body = json.dumps({"tables": [], "columns": [], "relationships": [],
                       "examples": []})
    app.openai_client = _SeqOpenAI(body)
    try:
        r = c.post("/admin/api/datahub/0/ai-define",
                   json={"tables": ["leads", "callback_requests"]},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200, r.get_data(as_text=True)
        r2 = c.post("/admin/api/datahub/0/ai-define",
                    json={"table": "leads", "column": "email"},
                    headers={"X-CSRF-Token": "t"})
        assert r2.status_code == 200, r2.get_data(as_text=True)
        assert r2.get_json().get("column") == "email"
    finally:
        app.openai_client = saved
        _wipe()


# ----- Cause-specific error messages (task 083 refinement) ------------------
# AI-define must tell the admin WHY a draft failed (bad/absent key vs rate-limit
# vs timeout vs a genuinely incomplete/oversized response) instead of always
# "try fewer tables". _dh_llm_draft classifies the exception into an err_sink
# that _dh_ai_define turns into the right message.

class _RaisingOpenAI:
    """Stub whose chat.completions.create raises a chosen exception."""
    def __init__(self, exc):
        self._exc = exc
        outer = self

        class _Comp:
            def create(self, **kw):
                raise outer._exc
        self.chat = type("C", (), {"completions": _Comp()})()

    def with_options(self, **kw):
        return self


def test_classify_llm_error():
    """The classifier buckets the common OpenAI failure modes (by type name +
    message, without importing the SDK's exception classes)."""
    assert app._dh_classify_llm_error(json.JSONDecodeError("Expecting value", "", 0)) == "incomplete"
    assert app._dh_classify_llm_error(Exception("Incorrect API key provided")) == "auth"
    assert app._dh_classify_llm_error(type("AuthenticationError", (Exception,), {})("nope")) == "auth"
    assert app._dh_classify_llm_error(Exception("Rate limit reached, code 429")) == "rate_limit"
    assert app._dh_classify_llm_error(Exception("Request timed out")) == "timeout"
    assert app._dh_classify_llm_error(ValueError("boom")) == "error"


def test_define_surfaces_auth_error_not_truncation():
    """A bad/absent key surfaces a key/config message — NOT 'try fewer tables'."""
    _wipe()
    saved = app.openai_client
    app.openai_client = _RaisingOpenAI(Exception("Incorrect API key provided: sk-xxx"))
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" in out, out
        assert "key" in out["error"].lower(), out
        assert "fewer tables" not in out["error"].lower(), out
    finally:
        app.openai_client = saved
        _wipe()


def test_define_incomplete_message_for_real_truncation():
    """A genuinely truncated/malformed JSON response keeps the 'try fewer tables'
    guidance (the real incomplete-response case)."""
    _wipe()
    saved = app.openai_client
    # Truncated JSON -> json.loads raises JSONDecodeError -> classified 'incomplete'.
    app.openai_client = _CaptureOpenAI('{"tables": [{"table": "lea')
    try:
        out = app._dh_ai_define(0, table="leads")
        assert "error" in out, out
        assert out["error"] == app._DH_DEFINE_ALL_FAILED, out
    finally:
        app.openai_client = saved
        _wipe()
