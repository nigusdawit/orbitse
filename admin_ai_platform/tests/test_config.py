"""Unit tests for the config layer + tenant resolution (no DB / no network)."""

import importlib

from admin_ai_platform import config


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("AAP_TEST_INT", "7")
    assert config.env_int("AAP_TEST_INT", 0) == 7
    monkeypatch.setenv("AAP_TEST_INT", "")           # empty → default
    assert config.env_int("AAP_TEST_INT", 3) == 3
    monkeypatch.delenv("AAP_TEST_INT", raising=False)
    assert config.env_int("AAP_TEST_INT", 9) == 9

    monkeypatch.setenv("AAP_TEST_BOOL", "yes")
    assert config.env_bool("AAP_TEST_BOOL") is True
    monkeypatch.setenv("AAP_TEST_BOOL", "0")
    assert config.env_bool("AAP_TEST_BOOL") is False


def test_env_int_invalid_raises(monkeypatch):
    monkeypatch.setenv("AAP_TEST_BAD", "banana")
    try:
        config.env_int("AAP_TEST_BAD", 1)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "AAP_TEST_BAD" in str(e)


def test_env_choice_falls_back(monkeypatch):
    monkeypatch.setenv("AAP_TEST_CHOICE", "nonsense")
    assert config.env_choice("AAP_TEST_CHOICE", ("a", "b"), "a") == "a"
    monkeypatch.setenv("AAP_TEST_CHOICE", "b")
    assert config.env_choice("AAP_TEST_CHOICE", ("a", "b"), "a") == "b"


def test_mode_defaults_self_host(monkeypatch):
    # Re-import config with explicit modes to verify the module-level resolution.
    monkeypatch.setenv("DEPLOY_MODE", "self_host")
    monkeypatch.setenv("ADMIN_MODE", "self_serve")
    importlib.reload(config)
    assert config.is_self_host() is True
    assert config.is_central() is False
    assert config.admin_is_self_serve() is True


def test_current_tenant_id_self_host(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "self_host")
    importlib.reload(config)
    from admin_ai_platform import tenancy
    importlib.reload(tenancy)
    assert tenancy.current_tenant_id() == config.DEFAULT_TENANT_ID
