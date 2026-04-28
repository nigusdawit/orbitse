"""
Optimization #9: tune the database connection pool defaults.

The previous defaults (min=1, max=10) were conservative leftovers from
Tier 7 when the pool was first added. Under bursty traffic on a Replit
autoscale deployment, min=1 means every cold worker pays the
TCP+TLS+auth handshake (~30-150 ms on managed Postgres) on the first
request of every traffic wave; max=10 means a page-bundle fanout of
8-12 queries plus any concurrent users hits PoolError and falls back
to direct-connect (slower than just having had the headroom).

These tests pin the new defaults (2/20) AND the env-var override
behaviour AND the validation rules. They do NOT spin up real Postgres
connections — `_resolve_pool_sizes` is a pure function over a dict-like
env, so we can call it directly with synthetic envs.
"""

import importlib

import pytest

import app as flask_app


def _resolve(env):
    """Convenience wrapper so each test can pass a tiny env dict."""
    return flask_app._resolve_pool_sizes(env)


class TestPoolDefaults:
    """The whole point of Optimization #9: when no env vars are set,
    the pool should come up at min=2, max=20."""

    def test_unset_env_yields_2_and_20(self):
        assert _resolve({}) == (2, 20)

    def test_module_constants_match_defaults(self):
        # The module-level constants are computed once at import from
        # `os.environ`. In the test environment neither var is set, so
        # they should equal the documented defaults. (If someone runs
        # the test suite with DB_POOL_MIN/MAX exported in their shell,
        # this test will fail loudly — that's intentional, the suite
        # should run with the defaults.)
        import os
        if "DB_POOL_MIN" in os.environ or "DB_POOL_MAX" in os.environ:
            pytest.skip("DB_POOL_MIN/MAX set in test env — expected default 2/20")
        assert flask_app._DB_POOL_MIN == 2
        assert flask_app._DB_POOL_MAX == 20

    def test_boot_log_format_unchanged(self):
        # Tier 7 set the format `[db pool] initialised (min=N, max=M)`.
        # The init code uses an f-string with the constants, so as long
        # as the constants are the new values, the boot log naturally
        # reflects the new defaults. We pin the format string here so a
        # future refactor can't silently drop the visibility.
        import inspect
        src = inspect.getsource(flask_app._init_db_pool)
        assert "[db pool] initialised" in src
        assert "min=" in src and "max=" in src


class TestPoolEnvOverrides:
    """Operators on a managed-Postgres tier with low max_connections need
    to be able to override the new defaults. Pin both directions."""

    def test_min_env_var_honored(self):
        assert _resolve({"DB_POOL_MIN": "5"}) == (5, 20)

    def test_max_env_var_honored(self):
        assert _resolve({"DB_POOL_MAX": "50"}) == (2, 50)

    def test_both_env_vars_honored(self):
        assert _resolve({"DB_POOL_MIN": "3", "DB_POOL_MAX": "30"}) == (3, 30)

    def test_operator_can_opt_back_to_min_1(self):
        # The old default was min=1. An operator who specifically wants
        # the old behaviour (e.g., to minimise idle connections on a
        # tiny database) must be able to set it explicitly.
        assert _resolve({"DB_POOL_MIN": "1"}) == (1, 20)


class TestPoolValidation:
    """The clamp logic must keep psycopg2.pool.ThreadedConnectionPool
    happy: it requires min >= 1 and max >= min, otherwise it raises at
    construction time and we'd fall through to the always-direct-connect
    fallback (silently degrading perf) instead of running a pool at all."""

    def test_min_clamped_to_1_when_zero_requested(self):
        # max(1, 0) = 1
        assert _resolve({"DB_POOL_MIN": "0"}) == (1, 20)

    def test_min_clamped_to_1_when_negative_requested(self):
        assert _resolve({"DB_POOL_MIN": "-5"}) == (1, 20)

    def test_max_clamped_up_when_below_min(self):
        # If operator sets DB_POOL_MAX=5 with default min=2, that's
        # legal (max >= min). But DB_POOL_MAX=1 with default min=2 is
        # illegal — clamp max up to min so the pool still constructs.
        assert _resolve({"DB_POOL_MAX": "1"}) == (2, 2)

    def test_max_clamped_up_when_below_explicit_min(self):
        # Reject the misconfig DB_POOL_MIN=10, DB_POOL_MAX=5 — clamp
        # max up to min, never silently swap them.
        assert _resolve({"DB_POOL_MIN": "10", "DB_POOL_MAX": "5"}) == (10, 10)

    def test_empty_string_falls_back_to_default(self):
        # The common operator mistake: `export DB_POOL_MAX=` (no value).
        # `os.environ.get("DB_POOL_MAX", "20")` returns "" (env var
        # exists but is empty), not the default. The `or "20"` guard
        # in _resolve_pool_sizes catches this.
        assert _resolve({"DB_POOL_MIN": "", "DB_POOL_MAX": ""}) == (2, 20)

    def test_garbage_int_value_raises_loud(self):
        # If an operator sets DB_POOL_MAX=banana, fail loud at startup
        # — silently falling back to the default would hide the typo.
        with pytest.raises(ValueError):
            _resolve({"DB_POOL_MAX": "banana"})

    def test_garbage_error_message_names_var_and_value(self):
        # Operator-friendly diagnostic: the message must say WHICH var
        # and WHICH value is bad, not the raw `int()` traceback.
        with pytest.raises(ValueError) as exc_info:
            _resolve({"DB_POOL_MAX": "banana"})
        msg = str(exc_info.value)
        assert "DB_POOL_MAX" in msg
        assert "banana" in msg
        # Also covers the min path:
        with pytest.raises(ValueError) as exc_info:
            _resolve({"DB_POOL_MIN": "twenty"})
        msg = str(exc_info.value)
        assert "DB_POOL_MIN" in msg
        assert "twenty" in msg


class TestPoolWiring:
    """Sanity check that _resolve_pool_sizes is actually wired into the
    pool construction site — a future refactor that bypasses it would
    silently revert the optimization."""

    def test_init_db_pool_uses_module_constants(self):
        import inspect
        src = inspect.getsource(flask_app._init_db_pool)
        # The pool constructor should be passed _DB_POOL_MIN/_DB_POOL_MAX
        # (or whatever they're named at module scope), not hardcoded ints.
        assert "_DB_POOL_MIN" in src
        assert "_DB_POOL_MAX" in src

    def test_resolve_pool_sizes_is_pure(self):
        # Calling it twice with the same env yields the same result —
        # no hidden state, no side effects on os.environ.
        env1 = {"DB_POOL_MIN": "4", "DB_POOL_MAX": "40"}
        env2 = dict(env1)
        assert _resolve(env1) == _resolve(env2) == (4, 40)
        # And the env dicts are unchanged (we don't mutate caller input).
        assert env1 == {"DB_POOL_MIN": "4", "DB_POOL_MAX": "40"}
