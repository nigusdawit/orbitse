"""
Tests for the ``env_manager`` module — the pure-helpers layer that
backs the admin Secrets tab.

These tests are 100 % filesystem + ``os.environ`` based — there is no
Flask app, no DB, no network. Every test points the module's
``ENV_FILE_PATH`` at a ``tmp_path`` file via monkeypatch so the real
``.env`` file (if any) is never touched.

Coverage
--------
* ``_parse_env_file`` — handles missing file, comments, blank lines,
  bare values, double-quoted values with escapes, single-quoted raw
  values, and an optional ``export`` prefix.
* ``_serialise_env_value`` — quotes values that contain whitespace or
  metacharacters; round-trips losslessly.
* ``_write_env_file_atomic`` — writes restrictive (0o600) permissions
  and the file is parseable back.
* ``load_env_file_into_environ`` — fills missing keys but **does not
  override** an already-set var (Replit Secrets win).
* ``_mask`` — short / empty / long values render correctly.
* ``get_status`` — sensitive vars are masked, non-sensitive vars show
  the raw value, ``source`` correctly distinguishes ``env_file`` vs
  ``replit_secret`` vs ``unset``.
* ``set_var`` — whitelist enforced, value-size guard, NUL-byte
  rejected, Replit-Secret-shadowed key REJECTED with explanatory
  error, happy-path round-trips through the file and ``os.environ``.
* ``unset_var`` — whitelist enforced, idempotent on already-unset,
  rejects when source is ``replit_secret``, happy-path clears both
  the file and ``os.environ``.
"""

import os
import stat

import pytest

import env_manager


# ---------------------------------------------------------------------------
# Fixture: redirect ENV_FILE_PATH to a tmp file and snapshot/restore the
# module-private _env_file_keys + os.environ for the keys we touch.
# ---------------------------------------------------------------------------

@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point env_manager at a fresh tmp .env file and isolate
    os.environ + the module-private _env_file_keys cache so tests
    don't bleed into each other or pollute the real environment."""
    path = tmp_path / ".env"
    monkeypatch.setattr(env_manager, "ENV_FILE_PATH", str(path))
    # Snapshot + restore _env_file_keys.
    saved_keys = set(env_manager._env_file_keys)
    env_manager._env_file_keys = set()

    # Keys we'll potentially mutate during the test — clear them up
    # front and remember what was there to restore at teardown.
    touched = (
        "PUBLIC_BASE_URL", "ADMIN_EMAIL", "ADMIN_PHONE",
        "RESEND_FROM_EMAIL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "STRIPE_SECRET_KEY", "STRIPE_TEST_SECRET_KEY",
        "BRAVE_SEARCH_API_KEY", "ELEVENLABS_API_KEY",
        "FORCE_SECURE_COOKIES", "SENTRY_ENV", "SITE_URL",
    )
    saved_env = {k: os.environ.get(k) for k in touched}
    for k in touched:
        os.environ.pop(k, None)

    yield path

    env_manager._env_file_keys = saved_keys
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestParser:
    def test_missing_file_returns_empty(self, env_file):
        assert env_manager._parse_env_file(str(env_file)) == {}

    def test_basic_kv_pair(self, env_file):
        env_file.write_text("FOO=bar\n")
        assert env_manager._parse_env_file(str(env_file)) == {"FOO": "bar"}

    def test_skips_blank_lines_and_comments(self, env_file):
        env_file.write_text("# a comment\n\nFOO=bar\n   # indented comment\nBAZ=qux\n")
        assert env_manager._parse_env_file(str(env_file)) == {"FOO": "bar", "BAZ": "qux"}

    def test_double_quoted_value_with_escapes(self, env_file):
        env_file.write_text(r'FOO="hello \"world\"  with spaces"' + "\n")
        out = env_manager._parse_env_file(str(env_file))
        assert out == {"FOO": 'hello "world"  with spaces'}

    def test_double_quoted_value_with_newline_escape(self, env_file):
        env_file.write_text(r'FOO="line1\nline2"' + "\n")
        out = env_manager._parse_env_file(str(env_file))
        assert out == {"FOO": "line1\nline2"}

    def test_single_quoted_value_is_raw(self, env_file):
        env_file.write_text("FOO='no \\n escaping here'\n")
        out = env_manager._parse_env_file(str(env_file))
        assert out == {"FOO": "no \\n escaping here"}

    def test_export_prefix_supported(self, env_file):
        env_file.write_text("export FOO=bar\n")
        assert env_manager._parse_env_file(str(env_file)) == {"FOO": "bar"}

    def test_inline_comment_after_bare_value(self, env_file):
        env_file.write_text("FOO=bar  # trailing\n")
        out = env_manager._parse_env_file(str(env_file))
        assert out == {"FOO": "bar"}

    def test_malformed_lines_silently_skipped(self, env_file):
        env_file.write_text("not a kv line\nFOO=bar\nALSO_BAD\n")
        out = env_manager._parse_env_file(str(env_file))
        assert out == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class TestWriter:
    def test_round_trip_simple(self, env_file):
        data = {"FOO": "bar", "BAZ": "qux"}
        env_manager._write_env_file_atomic(data, str(env_file))
        assert env_manager._parse_env_file(str(env_file)) == data

    def test_round_trip_special_chars(self, env_file):
        data = {
            "PLAIN": "simple",
            "WITH_SPACE": "hello world",
            "WITH_QUOTE": 'he said "hi"',
            "WITH_HASH": "value#nope",
            "WITH_NEWLINE": "a\nb",
            "WITH_DOLLAR": "$PATH",
            "EMPTY": "",
        }
        env_manager._write_env_file_atomic(data, str(env_file))
        assert env_manager._parse_env_file(str(env_file)) == data

    def test_writes_restrictive_perms(self, env_file):
        env_manager._write_env_file_atomic({"FOO": "bar"}, str(env_file))
        # 0o600 = owner read+write only. Only check on POSIX.
        if hasattr(os, "geteuid"):
            mode = stat.S_IMODE(os.stat(str(env_file)).st_mode)
            # Owner has rw, group/other should have nothing.
            assert mode & 0o077 == 0, f"world/group bits set: {oct(mode)}"

    def test_keys_sorted_alphabetically(self, env_file):
        env_manager._write_env_file_atomic({"BBB": "2", "AAA": "1", "CCC": "3"}, str(env_file))
        body = env_file.read_text()
        # Strip header comments + blank line, just look at KV ordering.
        # (Header line "# ... KEY=VALUE format." also contains '=', so we
        # explicitly filter comment lines out before splitting.)
        kv_lines = [
            ln for ln in body.splitlines()
            if "=" in ln and not ln.lstrip().startswith("#")
        ]
        keys = [ln.split("=", 1)[0] for ln in kv_lines]
        assert keys == ["AAA", "BBB", "CCC"]


# ---------------------------------------------------------------------------
# Loader (Replit Secrets > .env precedence)
# ---------------------------------------------------------------------------

class TestLoader:
    def test_fills_missing_keys(self, env_file):
        env_file.write_text("PUBLIC_BASE_URL=https://example.test\n")
        os.environ.pop("PUBLIC_BASE_URL", None)
        applied = env_manager.load_env_file_into_environ(str(env_file))
        assert applied == 1
        assert os.environ["PUBLIC_BASE_URL"] == "https://example.test"
        assert "PUBLIC_BASE_URL" in env_manager._env_file_keys

    def test_does_not_override_already_set(self, env_file):
        # Simulate a Replit Secret already in the env.
        os.environ["PUBLIC_BASE_URL"] = "https://from-replit.test"
        env_file.write_text("PUBLIC_BASE_URL=https://from-env-file.test\n")
        applied = env_manager.load_env_file_into_environ(str(env_file))
        assert applied == 0  # nothing was applied — already-set vars win
        assert os.environ["PUBLIC_BASE_URL"] == "https://from-replit.test"
        # The key MUST NOT be tracked as a .env-applied key when it
        # was shadowed by an existing os.environ value — otherwise
        # _classify_source would mis-report ``source=env_file`` and
        # set_var/unset_var would happily mutate a Replit-managed key.
        assert "PUBLIC_BASE_URL" not in env_manager._env_file_keys


# ---------------------------------------------------------------------------
# Shadowing — the highest-stakes path: a Replit Secret AND an entry in
# .env exist for the same key. The Replit Secret wins at runtime, and
# the in-app routes MUST refuse to mutate it.
# ---------------------------------------------------------------------------

class TestShadowedReplitSecret:
    def test_status_reports_source_as_replit_secret(self, env_file):
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        env_file.write_text("ADMIN_EMAIL=from-env-file@example.test\n")
        env_manager.load_env_file_into_environ(str(env_file))
        rows = env_manager.get_status()
        row = next(r for r in rows if r["key"] == "ADMIN_EMAIL")
        # Effective value is the Replit Secret, so source must reflect that.
        assert row["set"] is True
        assert row["source"] == "replit_secret"
        # Non-sensitive var → value is shown in clear, and it MUST be
        # the Replit value, not the .env value.
        assert row["value"] == "from-replit@example.test"

    def test_set_var_refuses_to_mutate_replit_managed_key(self, env_file):
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        env_file.write_text("ADMIN_EMAIL=from-env-file@example.test\n")
        env_manager.load_env_file_into_environ(str(env_file))
        with pytest.raises(env_manager.EnvManagerError, match="Replit Secrets"):
            env_manager.set_var("ADMIN_EMAIL", "from-app@example.test")
        # Replit value must be untouched.
        assert os.environ["ADMIN_EMAIL"] == "from-replit@example.test"

    def test_unset_var_refuses_to_pop_replit_managed_key(self, env_file):
        # This is the dangerous one: before the shadowing fix,
        # unset_var would happily pop ADMIN_EMAIL from os.environ,
        # silently removing the Replit-Secret-provided value from
        # the running process.
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        env_file.write_text("ADMIN_EMAIL=from-env-file@example.test\n")
        env_manager.load_env_file_into_environ(str(env_file))
        with pytest.raises(env_manager.EnvManagerError, match="Replit Secrets"):
            env_manager.unset_var("ADMIN_EMAIL")
        # CRITICAL: Replit value must still be in os.environ.
        assert os.environ.get("ADMIN_EMAIL") == "from-replit@example.test"


# ---------------------------------------------------------------------------
# Mask
# ---------------------------------------------------------------------------

class TestMask:
    def test_empty(self):
        assert env_manager._mask("") == ""

    def test_short_all_bullets(self):
        # ≤ 4 chars → all bullets, no clear chars at all.
        assert env_manager._mask("ab") == "••"
        assert env_manager._mask("abcd") == "••••"

    def test_long_last_four(self):
        assert env_manager._mask("sk_live_1234567890ABCDEF") == "••••CDEF"

    def test_never_returns_full_value(self):
        secret = "sk_live_supersecret_xyz1234"
        out = env_manager._mask(secret)
        # Only the last 4 chars may appear in the output.
        assert secret[:-4] not in out
        assert out.endswith(secret[-4:])


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_unset_var_renders_correctly(self, env_file):
        rows = env_manager.get_status()
        public = next(r for r in rows if r["key"] == "PUBLIC_BASE_URL")
        assert public["set"] is False
        assert public["source"] == "unset"
        assert public["value"] == ""
        assert public["masked"] == ""

    def test_sensitive_var_is_masked_never_clear(self, env_file):
        os.environ["OPENAI_API_KEY"] = "sk-ABCDEFG1234567890XYZ"
        env_manager._env_file_keys.add("OPENAI_API_KEY")
        rows = env_manager.get_status()
        row = next(r for r in rows if r["key"] == "OPENAI_API_KEY")
        assert row["set"] is True
        assert row["sensitive"] is True
        assert row["value"] == ""           # NEVER returns a clear sensitive value
        assert row["masked"] == "••••0XYZ"  # last 4 only

    def test_non_sensitive_var_returns_clear_value(self, env_file):
        os.environ["PUBLIC_BASE_URL"] = "https://example.test"
        env_manager._env_file_keys.add("PUBLIC_BASE_URL")
        rows = env_manager.get_status()
        row = next(r for r in rows if r["key"] == "PUBLIC_BASE_URL")
        assert row["value"] == "https://example.test"
        assert row["masked"] == ""

    def test_source_env_file_vs_replit_secret(self, env_file):
        # A var that's in env_file_keys → source=env_file.
        os.environ["PUBLIC_BASE_URL"] = "https://x.test"
        env_manager._env_file_keys.add("PUBLIC_BASE_URL")
        # A var that's in os.environ but NOT in env_file_keys → source=replit_secret.
        os.environ["ADMIN_EMAIL"] = "ops@example.test"
        rows = env_manager.get_status()
        public = next(r for r in rows if r["key"] == "PUBLIC_BASE_URL")
        admin_email = next(r for r in rows if r["key"] == "ADMIN_EMAIL")
        assert public["source"] == "env_file"
        assert admin_email["source"] == "replit_secret"

    def test_every_known_var_appears_exactly_once(self, env_file):
        rows = env_manager.get_status()
        keys = [r["key"] for r in rows]
        assert len(keys) == len(set(keys)), "duplicate key in get_status output"
        assert set(keys) == {v["key"] for v in env_manager.KNOWN_VARS}


# ---------------------------------------------------------------------------
# set_var
# ---------------------------------------------------------------------------

class TestSetVar:
    def test_rejects_unknown_key(self, env_file):
        with pytest.raises(env_manager.EnvManagerError, match="Unknown key"):
            env_manager.set_var("NOT_ON_THE_WHITELIST", "value")

    def test_rejects_non_string_value(self, env_file):
        with pytest.raises(env_manager.EnvManagerError, match="must be a string"):
            env_manager.set_var("PUBLIC_BASE_URL", 1234)  # type: ignore[arg-type]

    def test_rejects_nul_byte(self, env_file):
        with pytest.raises(env_manager.EnvManagerError, match="NUL"):
            env_manager.set_var("PUBLIC_BASE_URL", "value\x00inside")

    def test_rejects_oversize_value(self, env_file):
        with pytest.raises(env_manager.EnvManagerError, match="too long"):
            env_manager.set_var("PUBLIC_BASE_URL", "x" * 8193)

    def test_rejects_when_replit_secret_shadows_key(self, env_file):
        # Simulate a Replit Secret already providing the value.
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        # Note: NOT in _env_file_keys, so source is replit_secret.
        with pytest.raises(env_manager.EnvManagerError, match="Replit Secrets"):
            env_manager.set_var("ADMIN_EMAIL", "from-app@example.test")
        # Underlying value MUST be unchanged.
        assert os.environ["ADMIN_EMAIL"] == "from-replit@example.test"
        # And the .env file MUST NOT have been written.
        assert not env_file.exists()

    def test_happy_path_writes_file_and_environ(self, env_file):
        row = env_manager.set_var("PUBLIC_BASE_URL", "https://hello.test")
        # File round-trip
        parsed = env_manager._parse_env_file(str(env_file))
        assert parsed == {"PUBLIC_BASE_URL": "https://hello.test"}
        # In-process env updated
        assert os.environ["PUBLIC_BASE_URL"] == "https://hello.test"
        # Source flips to env_file
        assert "PUBLIC_BASE_URL" in env_manager._env_file_keys
        # Returned row reflects the new state
        assert row["set"] is True
        assert row["source"] == "env_file"
        assert row["value"] == "https://hello.test"

    def test_empty_string_is_allowed(self, env_file):
        # Useful for FORCE_SECURE_COOKIES="" to disable.
        row = env_manager.set_var("FORCE_SECURE_COOKIES", "")
        assert row["set"] is False  # empty string → not 'set' for status purposes
        # But the .env file does carry the explicit empty entry.
        assert env_manager._parse_env_file(str(env_file)) == {"FORCE_SECURE_COOKIES": ""}

    def test_overwrite_existing_env_file_value(self, env_file):
        env_manager.set_var("PUBLIC_BASE_URL", "https://first.test")
        env_manager.set_var("PUBLIC_BASE_URL", "https://second.test")
        assert os.environ["PUBLIC_BASE_URL"] == "https://second.test"
        assert env_manager._parse_env_file(str(env_file))["PUBLIC_BASE_URL"] == "https://second.test"

    def test_multiple_keys_coexist_in_file(self, env_file):
        env_manager.set_var("PUBLIC_BASE_URL", "https://a.test")
        env_manager.set_var("ADMIN_EMAIL", "ops@example.test")
        parsed = env_manager._parse_env_file(str(env_file))
        assert parsed == {
            "PUBLIC_BASE_URL": "https://a.test",
            "ADMIN_EMAIL": "ops@example.test",
        }


# ---------------------------------------------------------------------------
# unset_var
# ---------------------------------------------------------------------------

class TestUnsetVar:
    def test_rejects_unknown_key(self, env_file):
        with pytest.raises(env_manager.EnvManagerError, match="Unknown key"):
            env_manager.unset_var("NOT_ON_THE_WHITELIST")

    def test_idempotent_when_already_unset(self, env_file):
        # Should NOT raise — already unset is fine.
        row = env_manager.unset_var("PUBLIC_BASE_URL")
        assert row["set"] is False

    def test_rejects_when_replit_secret_provides_value(self, env_file):
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        # Not in _env_file_keys, so source=replit_secret.
        with pytest.raises(env_manager.EnvManagerError, match="Replit Secrets"):
            env_manager.unset_var("ADMIN_EMAIL")
        assert os.environ["ADMIN_EMAIL"] == "from-replit@example.test"

    def test_happy_path_clears_file_and_environ(self, env_file):
        env_manager.set_var("PUBLIC_BASE_URL", "https://x.test")
        env_manager.set_var("ADMIN_EMAIL", "ops@example.test")
        env_manager.unset_var("PUBLIC_BASE_URL")
        # Removed from os.environ
        assert "PUBLIC_BASE_URL" not in os.environ
        # Removed from .env file (but ADMIN_EMAIL remains)
        parsed = env_manager._parse_env_file(str(env_file))
        assert parsed == {"ADMIN_EMAIL": "ops@example.test"}
        # Tracking set updated
        assert "PUBLIC_BASE_URL" not in env_manager._env_file_keys


# ---------------------------------------------------------------------------
# known_keys
# ---------------------------------------------------------------------------

def test_known_keys_iterates_every_whitelisted_key():
    keys = list(env_manager.known_keys())
    assert len(keys) == len(env_manager.KNOWN_VARS)
    assert set(keys) == {v["key"] for v in env_manager.KNOWN_VARS}
