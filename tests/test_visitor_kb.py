"""Task 038 — visitor KB tool (audience-scoped). Embedded Postgres."""
import app


def test_tool_declared_and_dispatched():
    names = {t["function"]["name"] for t in app.CHAT_TOOLS}
    assert "lookup_knowledge_base" in names
    assert "lookup_knowledge_base" in app.CHAT_LOOKUP_FUNCTIONS


def test_visitor_kb_uses_visitor_surface(monkeypatch):
    captured = {}
    def fake_retrieve(q, **kw):
        captured.update(kw)
        return [{"filename": "f.pdf", "page_number": 2,
                 "content_text": "hello", "score": 0.9}]
    monkeypatch.setattr(app.rag, "retrieve", fake_retrieve)
    out = app.lookup_knowledge_base(query="policy")
    assert captured.get("surface") == "visitor"   # never sees admin-only docs
    assert out and out[0]["source"] == "f.pdf" and out[0]["page"] == 2


def test_empty_query_returns_empty():
    assert app.lookup_knowledge_base(query="") == []
    assert app.lookup_knowledge_base() == []


def test_skill_registered_and_visitor_chat_unaffected():
    # sync_ai_prompts/sync_skills ran at boot → the tool is a known skill.
    row = app.query_db(
        "SELECT name FROM agent_skills WHERE name='lookup_knowledge_base'",
        fetchone=True)
    assert row is not None, "visitor KB tool should be registered in agent_skills"
    # Visitor chat still streams (the new tool didn't break the loop).
    r = app.app.test_client().post("/api/chat",
                                   json={"session_id": "kbv-1", "message": "hi"})
    assert r.status_code == 200 and "data:" in r.get_data(as_text=True)
