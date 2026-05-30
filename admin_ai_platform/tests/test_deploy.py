"""Unit tests for M20 deploy helpers (pure, no DB/network).

The bundle build + snapshot round-trip run against real files/Postgres in the
gate; here we pin the snapshot row-coercion helpers that make arbitrary DB rows
JSON-serializable and INSERT-safe.
"""

import datetime
import decimal

from admin_ai_platform import snapshot


def test_jsonable_coerces_temporal_and_decimal():
    row = {
        "created_at": datetime.datetime(2026, 1, 2, 3, 4, 5),
        "the_date": datetime.date(2026, 1, 2),
        "the_time": datetime.time(9, 30),
        "amount": decimal.Decimal("12.50"),
        "name": "x", "n": 3, "ok": True, "nothing": None,
    }
    out = snapshot._jsonable(row)
    assert out["created_at"] == "2026-01-02T03:04:05"
    assert out["the_date"] == "2026-01-02"
    assert out["the_time"] == "09:30:00"
    assert out["amount"] == "12.50"           # Decimal -> str (json-safe)
    assert out["name"] == "x" and out["n"] == 3 and out["ok"] is True
    assert out["nothing"] is None


def test_insert_cols_skips_identity_and_encodes_json():
    cols, ph, vals = snapshot._insert_cols(
        "t", {"id": 7, "created_at": "x", "updated_at": "y",
              "slug": "s", "meta": {"a": 1}, "tags": ["x"]})
    assert "id" not in cols and "created_at" not in cols and "updated_at" not in cols
    assert "slug" in cols and "meta" in cols and "tags" in cols
    # dict/list columns are jsonb-cast.
    meta_i = cols.index("meta")
    assert ph[meta_i] == "%s::jsonb" and vals[meta_i] == '{"a": 1}'
    slug_i = cols.index("slug")
    assert ph[slug_i] == "%s" and vals[slug_i] == "s"


def test_redact_and_strategy_tables_consistent():
    # Every redacted table must be a known snapshot table.
    for t in snapshot._REDACT:
        assert t in snapshot._TABLES
    # Every table has a valid strategy.
    for spec in snapshot._TABLES.values():
        assert spec["strategy"] in ("singleton", "slug", "name", "append_if_empty")
        if spec["strategy"] in ("slug", "name"):
            assert "key" in spec
