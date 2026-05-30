"""Unit tests for M22 fleet-sync bundle signing (pure, no DB/network).

The versioned-merge apply + override/force flow run against a real Postgres in
the gate; here we pin the signature scheme, which is the security boundary for
the master->fleet control channel.
"""

from admin_ai_platform import fleet
from admin_ai_platform import config


def test_canonical_excludes_signature_and_is_deterministic():
    b = {"bundle_version": 3, "items": [{"item_key": "x", "version": 1}], "signature": "ZZZ"}
    c1 = fleet.canonical(b)
    c2 = fleet.canonical(dict(b))
    assert c1 == c2
    assert "ZZZ" not in c1            # signature field excluded from the signed payload
    assert "signature" not in c1


def test_sign_verify_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "topsecret")
    b = {"bundle_version": 1, "items": []}
    b["signature"] = fleet.sign_bundle(b)
    assert fleet.verify_signature(b) is True


def test_tampered_bundle_fails(monkeypatch):
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "topsecret")
    b = {"bundle_version": 1, "items": [{"item_key": "a", "version": 1, "value": "x"}]}
    b["signature"] = fleet.sign_bundle(b)
    # Mutate a field after signing → signature must no longer verify.
    b["items"][0]["value"] = "tampered"
    assert fleet.verify_signature(b) is False


def test_wrong_secret_fails(monkeypatch):
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "secret-A")
    b = {"bundle_version": 1, "items": []}
    b["signature"] = fleet.sign_bundle(b, "secret-A")
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "secret-B")
    assert fleet.verify_signature(b) is False


def test_no_secret_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "")
    b = {"bundle_version": 1, "items": [], "signature": "anything"}
    assert fleet.verify_signature(b) is False


def test_missing_signature_fails(monkeypatch):
    monkeypatch.setattr(config, "VELO_SHARED_SECRET", "topsecret")
    assert fleet.verify_signature({"bundle_version": 1, "items": []}) is False
