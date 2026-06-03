"""Task 084 — Sentry error-tracking hardening.

Runs under the embedded-Postgres harness (_runner.py). NO real SENTRY_DSN is
needed: the harness never sets one, so Sentry stays uninitialised and we test
the pure helper functions (before_send + release derivation) plus the
super-admin mute toggle directly. These tests assert the load-bearing
guarantees of the plan:

  (a) with no DSN, Sentry is NOT active (no client) — i.e. a strict no-op;
  (b) before_send DROPS a synthetic Werkzeug 4xx HTTPException and a
      BrokenPipeError, and KEEPS a normal application error;
  (c) the error_tracking_enabled toggle: OFF -> before_send returns None;
      default ON -> returns the event; and it FAILS OPEN (returns the event)
      if the toggle read raises;
  (d) the release-derivation helper NEVER raises and returns str-or-None.

The before_send + release-derivation logic is factored into module-level
functions/constants in app.py (_sentry_before_send / _derive_sentry_release /
SENTRY_RELEASE) precisely so this test can import and call them with no live
Sentry client.
"""
import os

import pytest
import sentry_sdk
from werkzeug.exceptions import NotFound, Forbidden, InternalServerError

import app


def _hint_for(exc):
    """Build a before_send `hint` shaped exactly like the Sentry SDK passes it:
    {"exc_info": (type, value, traceback)}. before_send reads exc_info[1]."""
    return {"exc_info": (type(exc), exc, None)}


def _event():
    """A minimal, distinguishable synthetic event dict."""
    return {"event_id": "deadbeef", "level": "error"}


# ---------------------------------------------------------------------------
# (a) No DSN in the harness -> Sentry must be a strict no-op (no active client)
# ---------------------------------------------------------------------------

def test_no_dsn_means_sentry_inactive():
    # The test harness never sets SENTRY_DSN, so init() was skipped entirely.
    assert not os.environ.get("SENTRY_DSN"), \
        "this test asserts the no-DSN path; unset SENTRY_DSN to run it"
    client = sentry_sdk.get_client()
    # v2.x API: get_client().is_active() is False when no DSN was configured.
    assert client.is_active() is False
    # And capture_exception is a harmless no-op (must not raise).
    try:
        raise ValueError("synthetic — should go nowhere")
    except ValueError as e:
        sentry_sdk.capture_exception(e)  # no client -> dropped silently


# ---------------------------------------------------------------------------
# (b) before_send noise filter: drop 4xx HTTPException + disconnects, keep real
# ---------------------------------------------------------------------------

def test_before_send_drops_4xx_httpexception():
    # 404 / 403 are normal client errors, not application bugs -> drop.
    assert app._sentry_before_send(_event(), _hint_for(NotFound())) is None
    assert app._sentry_before_send(_event(), _hint_for(Forbidden())) is None


def test_before_send_keeps_5xx_httpexception():
    # A 5xx HTTPException IS a real server error -> keep.
    ev = _event()
    assert app._sentry_before_send(ev, _hint_for(InternalServerError())) is ev


def test_before_send_drops_client_disconnects():
    for exc in (BrokenPipeError(), ConnectionResetError(), GeneratorExit()):
        assert app._sentry_before_send(_event(), _hint_for(exc)) is None, exc


def test_before_send_keeps_normal_exception():
    ev = _event()
    out = app._sentry_before_send(ev, _hint_for(RuntimeError("boom")))
    assert out is ev  # a genuine error is sent unchanged


def test_before_send_keeps_event_with_no_exc_info():
    # Message events (no exception) carry no exc_info -> keep them.
    ev = _event()
    assert app._sentry_before_send(ev, {}) is ev
    assert app._sentry_before_send(ev, None) is ev


def test_before_send_adds_no_pii():
    # Privacy: before_send must return the event UNCHANGED (no PII injected).
    ev = _event()
    out = app._sentry_before_send(ev, _hint_for(RuntimeError("boom")))
    assert out == {"event_id": "deadbeef", "level": "error"}


# ---------------------------------------------------------------------------
# (c) The super-admin mute toggle (error_tracking_enabled)
# ---------------------------------------------------------------------------

def _reset_toggle():
    try:
        app.reset_ai_setting("error_tracking_enabled")
    except Exception:
        pass
    app._invalidate_ai_control()


def test_toggle_default_on_sends_event():
    _reset_toggle()
    # Default (no DB override, env unset in harness) -> True -> keep the event.
    assert app.get_ai_setting("error_tracking_enabled") is True
    ev = _event()
    assert app._sentry_before_send(ev, _hint_for(RuntimeError("boom"))) is ev


def test_toggle_off_drops_all_events():
    _reset_toggle()
    app.set_ai_setting("error_tracking_enabled", False, by="test")
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("error_tracking_enabled") is False
        # Muted: even a genuine error is dropped.
        assert app._sentry_before_send(_event(), _hint_for(RuntimeError("boom"))) is None
        # ...and message events too.
        assert app._sentry_before_send(_event(), {}) is None
    finally:
        _reset_toggle()


def test_toggle_survives_ai_master_kill():
    """error_tracking_enabled is deliberately NOT in _AI_INERT, so flipping the
    AI master switch OFF must NOT mute error tracking (observability survives
    AI-off). Verifies the plan's key safety property at the registry level."""
    assert "error_tracking_enabled" not in app._AI_INERT
    _reset_toggle()
    try:
        app.set_ai_setting("ai_enhancements_enabled", False, by="test")
        app._invalidate_ai_control()
        # Master OFF, but error tracking falls through to env/default (True).
        assert app.get_ai_setting("error_tracking_enabled") is True
        ev = _event()
        assert app._sentry_before_send(ev, _hint_for(RuntimeError("boom"))) is ev
    finally:
        try:
            app.reset_ai_setting("ai_enhancements_enabled")
        except Exception:
            pass
        _reset_toggle()


def test_before_send_fails_open_when_toggle_read_raises(monkeypatch):
    """If the toggle read itself blows up, before_send must FAIL OPEN (send the
    event) rather than silently dropping real errors."""
    def _boom(_key):
        raise RuntimeError("DB exploded")
    monkeypatch.setattr(app, "get_ai_setting", _boom)
    ev = _event()
    # Toggle unreadable -> fall through to SEND a normal error.
    assert app._sentry_before_send(ev, _hint_for(RuntimeError("boom"))) is ev
    # The noise filter still applies on top of the fail-open toggle read.
    assert app._sentry_before_send(_event(), _hint_for(NotFound())) is None


def test_before_send_never_raises_on_garbage_hint():
    # A malformed hint must not crash before_send; fail-open -> return the event.
    ev = _event()
    assert app._sentry_before_send(ev, {"exc_info": "not-a-tuple"}) is ev
    assert app._sentry_before_send(ev, {"exc_info": (None, None, None)}) is ev


# ---------------------------------------------------------------------------
# (d) Release derivation never raises
# ---------------------------------------------------------------------------

def test_derive_release_never_raises_and_returns_str_or_none():
    rel = app._derive_sentry_release()
    assert rel is None or isinstance(rel, str)
    # The module-level constant is computed once and must satisfy the same.
    assert app.SENTRY_RELEASE is None or isinstance(app.SENTRY_RELEASE, str)


def test_derive_release_prefers_env(monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "v1.2.3-test")
    assert app._derive_sentry_release() == "v1.2.3-test"


def test_derive_release_survives_broken_git(monkeypatch):
    # No env override + a PATH with no `git` must still not raise (-> None or a
    # cached SHA from a prior call; both acceptable, neither raises).
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("PATH", "")
    rel = app._derive_sentry_release()
    assert rel is None or isinstance(rel, str)
