"""Task 098 (gap §3.6) — voice call KPIs. Embedded Postgres (no mocks).

/admin/api/voice-stats returns calls_7d / total / by_status / missed; super-admin only.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_voice_stats_shape_and_counts():
    c = _sa()
    app.execute_db("INSERT INTO voice_calls (call_sid, status, created_at) VALUES ('vs-1','completed',NOW())")
    app.execute_db("INSERT INTO voice_calls (call_sid, status, created_at) VALUES ('vs-2','missed',NOW())")
    app.execute_db("INSERT INTO voice_calls (call_sid, status, created_at) "
                   "VALUES ('vs-3','completed',NOW() - INTERVAL '30 days')")
    try:
        j = c.get("/admin/api/voice-stats").get_json()
        for k in ("calls_7d", "total", "by_status", "missed"):
            assert k in j
        assert j["calls_7d"] >= 2 and j["total"] >= 3   # 2 today, 1 old
        assert j["missed"] >= 1                          # the 'missed' row
        assert isinstance(j["by_status"], dict)
    finally:
        app.execute_db("DELETE FROM voice_calls WHERE call_sid IN ('vs-1','vs-2','vs-3')")


def test_voice_stats_super_gate():
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    assert cc.get("/admin/api/voice-stats").status_code == 403
