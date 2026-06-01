"""Task 057 — render_chart tool (in-chat chart spec). Embedded Postgres.

Unit-tests the spec normalization/bounding the backend tool produces; the
inline Chart.js rendering itself is frontend (syntax-checked separately, and
exercised via the live admin chat)."""
import app


def test_line_chart_normalizes_and_coerces():
    out = app._admin_tool_render_chart(spec={
        "type": "line", "title": "Sales", "labels": ["Jan", "Feb"],
        "values": ["10", 20, "oops"]})
    c = out["chart"]
    assert out["ok"] is True and c["type"] == "line" and c["title"] == "Sales"
    assert c["labels"] == ["Jan", "Feb"]
    assert c["values"] == [10.0, 20.0, 0.0]   # strings coerced, junk -> 0.0


def test_individual_fields_supported():
    out = app._admin_tool_render_chart(type="bar", title="T", labels=["a"], values=[1])
    assert out["chart"]["type"] == "bar" and out["chart"]["values"] == [1.0]


def test_kpi_and_table():
    k = app._admin_tool_render_chart(spec={"type": "kpi", "value": 42, "label": "Leads"})
    assert k["chart"]["type"] == "kpi" and k["chart"]["value"] == 42 and k["chart"]["label"] == "Leads"
    t = app._admin_tool_render_chart(spec={"type": "table", "columns": ["a", "b"],
                                           "rows": [[1, 2], [3, 4]]})
    assert t["chart"]["columns"] == ["a", "b"] and len(t["chart"]["rows"]) == 2


def test_unknown_type_falls_back_to_bar():
    assert app._admin_tool_render_chart(spec={"type": "pie"})["chart"]["type"] == "bar"


def test_bounds_capped():
    big = app._admin_tool_render_chart(spec={
        "type": "bar", "labels": [str(i) for i in range(500)],
        "values": list(range(500))})
    assert len(big["chart"]["labels"]) == 200 and len(big["chart"]["values"]) == 200


def test_tool_registered():
    assert "render_chart" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "render_chart" in names
