"""Unit tests for the M15 analytics UA parser (pure, no DB/network).

Tracking + aggregation run against a real Postgres in the gate; here we pin the
User-Agent → (device, browser, os) classification that feeds the dashboards.
"""

from admin_ai_platform.blueprints.analytics import _parse_ua


def test_iphone_safari():
    d, b, o = _parse_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605 Version/17.0 Mobile/15E148 Safari/604.1")
    assert d == "mobile" and b == "Safari" and o == "iOS"


def test_windows_chrome_desktop():
    d, b, o = _parse_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537 "
                        "Chrome/120.0 Safari/537")
    assert d == "desktop" and b == "Chrome" and o == "Windows"


def test_ipad_is_tablet():
    d, _, o = _parse_ua("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) Safari/604")
    assert d == "tablet" and o == "iOS"


def test_android_firefox():
    d, b, o = _parse_ua("Mozilla/5.0 (Android 13; Mobile) Gecko Firefox/119.0")
    assert d == "mobile" and b == "Firefox" and o == "Android"


def test_edge_on_windows():
    _, b, _ = _parse_ua("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120.0")
    assert b == "Edge"   # Edge must win over the Chrome token it also carries


def test_empty_ua_defaults_desktop_other():
    assert _parse_ua("") == ("desktop", "Other", "Other")
