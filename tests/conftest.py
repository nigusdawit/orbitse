"""
Shared pytest fixtures for the smoke suite.

Importing the Flask app is genuinely expensive — it runs `init_db()` against
the live database (idempotent CREATE TABLE IF NOT EXISTS only — never an
ALTER), starts the messaging + automations background scheduler threads,
imports velo_handlers which registers ~30 capabilities, and mounts the velo
blueprint. So we boot the app exactly once per pytest session and hand out
fresh test_clients to each test (each test_client has its own cookie jar,
which keeps CSRF/login state isolated between tests).

The Flask test_client uses Werkzeug's WSGI plumbing directly — no socket,
no port — so these tests can run alongside the regular `python app.py`
workflow without colliding on port 5000. The dev database IS shared though,
so every test in this file is intentionally read-only or sends a
deliberately-invalid POST that exercises the validation path without
mutating real data.
"""

import os
import sys

import pytest

# Make sure we can `import app` from the repo root regardless of where
# pytest was launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def flask_app():
    """Boot the Flask app once for the whole test session."""
    from app import app as _app  # heavy import; runs init_db() + spawns threads
    _app.config["TESTING"] = True
    yield _app


@pytest.fixture()
def client(flask_app):
    """Fresh test_client per test so cookies / sessions don't leak."""
    return flask_app.test_client()


@pytest.fixture(scope="session")
def velo_auth_headers():
    """Authorization headers VELO Master would send.

    VELO_AGENT_KEY is exposed as a deployment secret, so it leaks into
    the pytest env and verify_velo_key() rejects unauthenticated calls
    with 401. Tests that exercise the velo blueprint must send this
    bearer header to reach the actual handler logic.

    Returns the literal headers dict expected by Flask test_client; the
    Content-Type is set so json= keyword still works on POST calls.
    """
    key = os.environ.get("VELO_AGENT_KEY", "").strip()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
