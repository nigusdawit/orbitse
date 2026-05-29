"""Unit tests for the M10 scheduler-tick pure helpers (no DB / no network).

Only the next-run computation is pure enough to test without a database; the
tick *dispatch* behavior is exercised against a real Postgres in the gate
runner. Here we pin the schedule arithmetic so a regression in window/interval
math is caught fast.
"""

from datetime import datetime, timedelta

from admin_ai_platform.blueprints.scraper import _compute_next_run


def test_interval_mode_adds_minutes():
    base = datetime(2026, 1, 1, 12, 0, 0)
    nxt = _compute_next_run({"schedule_mode": "interval", "interval_minutes": 45}, base)
    assert nxt == base + timedelta(minutes=45)


def test_interval_zero_falls_back_to_hourly():
    # 0 is not a sane interval; the helper treats it as "use the hourly default".
    base = datetime(2026, 1, 1, 12, 0, 0)
    nxt = _compute_next_run({"schedule_mode": "interval", "interval_minutes": 0}, base)
    assert nxt == base + timedelta(minutes=60)


def test_daily_mode_targets_time_and_is_future():
    # 13:00 base, target 09:00 → must roll to next day's 09:00.
    base = datetime(2026, 1, 1, 13, 0, 0)
    nxt = _compute_next_run({"schedule_mode": "daily", "daily_time": "09:00"}, base)
    assert nxt == datetime(2026, 1, 2, 9, 0, 0)


def test_daily_mode_same_day_when_time_still_ahead():
    base = datetime(2026, 1, 1, 7, 0, 0)
    nxt = _compute_next_run({"schedule_mode": "daily", "daily_time": "09:00"}, base)
    assert nxt == datetime(2026, 1, 1, 9, 0, 0)


def test_weekly_mode_lands_on_requested_dow():
    # 2026-01-01 is a Thursday (weekday 3). Ask for Monday (0) at 09:00.
    base = datetime(2026, 1, 1, 12, 0, 0)
    nxt = _compute_next_run(
        {"schedule_mode": "weekly", "weekly_dow": 0, "daily_time": "09:00"}, base)
    assert nxt.weekday() == 0
    assert nxt > base
    assert (nxt.hour, nxt.minute) == (9, 0)


def test_malformed_config_falls_back_to_one_hour():
    base = datetime(2026, 1, 1, 12, 0, 0)
    nxt = _compute_next_run({"schedule_mode": "daily", "daily_time": "not-a-time"}, base)
    assert nxt == base + timedelta(minutes=60)
