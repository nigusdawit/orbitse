"""Unit test for the M12 lookup_events seats math (DB stubbed, no network).

The full RSVP/capacity/webhook flow runs against a real Postgres in the gate;
here we pin the seats_remaining computation (capacity minus held guests, and the
unlimited-capacity → None case) without a database.
"""

from admin_ai_platform import tools


def _patch_db(monkeypatch, events, taken):
    """Stub tools.query_db: the events SELECT returns ``events``; the per-event
    SUM(guests) count returns ``taken``."""
    def fake_query_db(sql, params=None, fetchone=False):
        if "FROM events" in sql:
            return list(events)
        if "SUM(guests)" in sql:
            return {"n": taken}
        return [] if not fetchone else None
    monkeypatch.setattr(tools, "query_db", fake_query_db)


def test_seats_remaining_capped(monkeypatch):
    _patch_db(monkeypatch, [{"id": 1, "slug": "gala", "title": "Gala", "description": "",
                             "start_at": None, "location": "", "capacity": 10,
                             "price_mode": "free", "price_cents": 0, "currency": "usd"}],
              taken=4)
    out = tools.lookup_events(slug="gala")
    assert out[0]["seats_remaining"] == 6


def test_seats_remaining_unlimited_is_none(monkeypatch):
    _patch_db(monkeypatch, [{"id": 2, "slug": "open", "title": "Open House", "description": "",
                             "start_at": None, "location": "", "capacity": 0,
                             "price_mode": "free", "price_cents": 0, "currency": "usd"}],
              taken=100)
    out = tools.lookup_events(slug="open")
    assert out[0]["seats_remaining"] is None


def test_sold_out_clamps_to_zero(monkeypatch):
    _patch_db(monkeypatch, [{"id": 3, "slug": "tiny", "title": "Tiny", "description": "",
                             "start_at": None, "location": "", "capacity": 2,
                             "price_mode": "paid", "price_cents": 500, "currency": "usd"}],
              taken=5)  # oversubscribed in data → must not go negative
    out = tools.lookup_events(slug="tiny")
    assert out[0]["seats_remaining"] == 0
