"""Unit tests for M14 integration pure helpers (no DB / no network).

The end-to-end admin flows run against a real Postgres in the gate; here we pin
the provider-payload parsers and the static registries that the routes depend on.
"""

from admin_ai_platform.blueprints import reviews
from admin_ai_platform.blueprints import mcp
from admin_ai_platform.blueprints import messaging
from admin_ai_platform.blueprints import presentations


def test_google_parser_legacy_and_new_shapes():
    assert reviews._parse_google(
        {"result": {"rating": 4.5, "user_ratings_total": 120}}) == (120, 4.5)
    # Places API (New) field names, no nested "result".
    assert reviews._parse_google({"rating": 4.2, "userRatingCount": 9}) == (9, 4.2)


def test_google_parser_missing_fields_default_zero():
    assert reviews._parse_google({}) == (0, 0.0)


def test_yelp_and_tripadvisor_parsers():
    assert reviews._parse_yelp({"rating": 4.0, "review_count": 88}) == (88, 4.0)
    assert reviews._parse_tripadvisor({"rating": 3.5, "num_reviews": 12}) == (12, 3.5)


def test_mcp_connector_blueprints_have_oauth_endpoints():
    assert "notion" in mcp.CONNECTOR_BLUEPRINTS
    for cfg in mcp.CONNECTOR_BLUEPRINTS.values():
        assert cfg["authorize_url"].startswith("https://")
        assert cfg["token_url"].startswith("https://")
        assert "label" in cfg


def test_sms_keyword_sets_are_disjoint_and_lowercase():
    assert mcp  # keep import meaningful
    assert messaging._SMS_STOP.isdisjoint(messaging._SMS_START)
    assert all(w == w.lower() for w in messaging._SMS_STOP | messaging._SMS_START)
    assert "stop" in messaging._SMS_STOP and "start" in messaging._SMS_START


def test_import_slug_derivation(monkeypatch):
    monkeypatch.setattr(presentations, "query_db", lambda *a, **k: None)
    assert presentations._unique_slug("My Great Deck!") == "my-great-deck"
    assert presentations._unique_slug("") == "deck"


def test_import_slug_appends_on_collision(monkeypatch):
    taken = {"my-deck"}  # base collides; "-2" is free

    def fake_query_db(sql, params=None, fetchone=False):
        return {"x": 1} if params and params[0] in taken else None
    monkeypatch.setattr(presentations, "query_db", fake_query_db)
    assert presentations._unique_slug("My Deck") == "my-deck-2"


def test_import_extensions_allowlist():
    assert ".pptx" in presentations._IMPORT_EXT
    assert ".txt" not in presentations._IMPORT_EXT
