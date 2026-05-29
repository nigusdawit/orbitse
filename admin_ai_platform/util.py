"""
admin_ai_platform.util
=====================

Small request/UA helpers shared across blueprints (independent copies of the
heuristics in the original app / kit). No framework state beyond the current
Flask request.
"""

from __future__ import annotations

from flask import request


def parse_ua(ua_string: str):
    """Return (browser, os, device_type) from a User-Agent string. Heuristic,
    good enough for analytics — not a full UA database."""
    ua = (ua_string or "").lower()
    browser = "Other"
    if "edg" in ua:
        browser = "Edge"
    elif "chrome" in ua and "edg" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    os_name = "Other"
    if "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "linux" in ua:
        os_name = "Linux"
    device = "mobile" if any(m in ua for m in ("mobile", "android", "iphone")) else "desktop"
    return browser, os_name, device


def client_ip() -> str:
    """Best-effort client IP, honoring the first X-Forwarded-For hop."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return (request.remote_addr or "")[:45]
