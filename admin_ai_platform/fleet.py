"""
admin_ai_platform.fleet
=======================

Fleet sync (M22) — the master→instance control plane for the **silo** fleet.

Under silo, each client runs its own instance + DB. This module lets the agency
master push **managed defaults** (system prompts, skill text, templates, presets)
to every install over the VELO channel, while each client's own edits live in
their DB and are never lost. The conflict policy is **versioned merge**:

  * every managed item carries a monotonic ``version``;
  * a client edit pins a ``local_value`` (``is_overridden=true``) stamped with the
    ``master_version`` it diverged from;
  * a normal master push updates only items the client hasn't overridden;
  * a master push with ``force=true`` and a HIGHER version than the override can
    win past a client edit — and the client's prior value is preserved as an
    **override-of-record** in ``managed_override_history`` (never silently lost).

Bundles are authenticated by an **HMAC-SHA256 signature over the canonical JSON**
(key = ``VELO_SHARED_SECRET``) and protected against replay/downgrade by a
**monotonic bundle_version** recorded in ``fleet_bundles`` (a bundle whose version
is <= the latest applied is rejected). No secret => the surface is disabled
(fail closed).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from . import config, __version__
from .db import query_db, execute_db


# ---- bundle signing / verification -------------------------------------
def canonical(bundle: dict) -> str:
    """Deterministic JSON for signing: sorted keys, no whitespace. The signature
    is computed over the bundle WITHOUT its ``signature`` field."""
    b = {k: v for k, v in (bundle or {}).items() if k != "signature"}
    return json.dumps(b, sort_keys=True, separators=(",", ":"))


def sign_bundle(bundle: dict, secret: str = None) -> str:
    """Return the base64 HMAC-SHA256 signature for a bundle. Used by the master
    (and the tests) to produce a signed bundle."""
    secret = secret if secret is not None else config.VELO_SHARED_SECRET
    mac = hmac.new(str(secret).encode(), canonical(bundle).encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def verify_signature(bundle: dict) -> bool:
    """Constant-time-verify a bundle's signature against VELO_SHARED_SECRET.
    Returns False when no secret is configured (fail closed) or the sig is bad."""
    secret = config.VELO_SHARED_SECRET
    if not secret:
        return False
    sent = (bundle or {}).get("signature") or ""
    if not sent:
        return False
    expected = sign_bundle(bundle, secret)
    return hmac.compare_digest(str(sent), expected)


# ---- versioned-merge apply ---------------------------------------------
def _latest_bundle_version() -> int:
    row = query_db("SELECT COALESCE(MAX(bundle_version),0) AS v FROM fleet_bundles",
                   fetchone=True)
    return int((row or {}).get("v", 0))


def apply_bundle(bundle: dict) -> dict:
    """Apply a (already signature-verified) bundle with versioned-merge semantics.
    Idempotent + monotonic: a bundle_version <= the latest applied is a no-op.
    Returns a summary dict."""
    try:
        bundle_version = int(bundle.get("bundle_version"))
    except (TypeError, ValueError):
        return {"applied": False, "error": "bundle_version required (int)"}
    if bundle_version <= _latest_bundle_version():
        return {"applied": False, "reason": "stale or duplicate bundle_version",
                "bundle_version": bundle_version}

    items = bundle.get("items") or []
    result = {"applied": True, "bundle_version": bundle_version,
              "created": 0, "updated_following_master": 0,
              "kept_local_override": 0, "forced_past_override": 0}
    for item in items:
        _apply_item(item, result)

    # Optional gradual-rollout feature flags carried by the bundle.
    for feat in (bundle.get("features") or []):
        try:
            _apply_feature_flag(feat)
        except Exception as e:
            print(f"[fleet] feature flag skipped: {e}")

    execute_db("INSERT INTO fleet_bundles (bundle_version, item_count, note) "
               "VALUES (%s,%s,%s) ON CONFLICT (bundle_version) DO NOTHING",
               (bundle_version, len(items), (bundle.get("note") or "")[:500]))
    return result


def _apply_item(item, result):
    key = (item.get("item_key") or "").strip()
    if not key:
        return
    version = int(item.get("version") or 0)
    value = item.get("value")
    force = bool(item.get("force"))
    category = (item.get("category") or "")[:40]
    vjson = json.dumps(value)

    existing = query_db("SELECT master_version, is_overridden, override_version, local_value "
                        "FROM managed_defaults WHERE item_key=%s", (key,), fetchone=True)
    if not existing:
        execute_db(
            "INSERT INTO managed_defaults (item_key, category, master_version, master_value) "
            "VALUES (%s,%s,%s,%s::jsonb)", (key, category, version, vjson))
        result["created"] += 1
        return

    # Always learn the latest master default + version.
    if not existing["is_overridden"]:
        # Client follows master → take the new default.
        execute_db("UPDATE managed_defaults SET category=%s, master_version=%s, "
                   "master_value=%s::jsonb, updated_at=NOW() WHERE item_key=%s",
                   (category, version, vjson, key))
        result["updated_following_master"] += 1
        return

    # Overridden. Master can force past it only with a strictly newer version.
    ov = existing["override_version"] or 0
    if force and version > ov:
        # Preserve the client's value as an override-of-record, then master wins.
        execute_db(
            "INSERT INTO managed_override_history (item_key, local_value, override_version, "
            " superseded_by_version) VALUES (%s,%s::jsonb,%s,%s)",
            (key, json.dumps(existing["local_value"]), ov, version))
        execute_db("UPDATE managed_defaults SET category=%s, master_version=%s, "
                   "master_value=%s::jsonb, local_value=NULL, is_overridden=FALSE, "
                   "override_version=NULL, updated_at=NOW() WHERE item_key=%s",
                   (category, version, vjson, key))
        result["forced_past_override"] += 1
    else:
        # Keep the client's override, but record that a newer master default
        # exists (so the admin UI can surface "update available, you've changed
        # this"). We update master_value/version but leave local_value intact.
        execute_db("UPDATE managed_defaults SET category=%s, master_version=%s, "
                   "master_value=%s::jsonb, updated_at=NOW() WHERE item_key=%s",
                   (category, version, vjson, key))
        result["kept_local_override"] += 1


def _apply_feature_flag(feat):
    from .tenancy import current_tenant_id
    name = feat.get("name")
    if not name:
        return
    execute_db(
        "INSERT INTO tenant_features (tenant_id, feature_name, enabled) VALUES (%s,%s,%s) "
        "ON CONFLICT (tenant_id, feature_name) DO UPDATE SET enabled=EXCLUDED.enabled, "
        "updated_at=NOW()",
        (current_tenant_id(), name, bool(feat.get("enabled", True))))


# ---- client-side override controls -------------------------------------
def set_local_override(item_key: str, value) -> bool:
    """Client edits a managed default: pin a local value, stamped with the master
    version it diverged from. Returns False if the item isn't a known managed
    default (master must seed it first)."""
    row = query_db("SELECT master_version FROM managed_defaults WHERE item_key=%s",
                   (item_key,), fetchone=True)
    if not row:
        return False
    execute_db("UPDATE managed_defaults SET local_value=%s::jsonb, is_overridden=TRUE, "
               "override_version=%s, updated_at=NOW() WHERE item_key=%s",
               (json.dumps(value), row["master_version"], item_key))
    return True


def reset_override(item_key: str) -> bool:
    """Clear a client override → follow the master default again."""
    row = execute_db("UPDATE managed_defaults SET local_value=NULL, is_overridden=FALSE, "
                     "override_version=NULL, updated_at=NOW() WHERE item_key=%s "
                     "RETURNING item_key", (item_key,))
    return bool(row)


def effective_value(item_key: str):
    """The value a consumer should use: the local override if set, else the
    master default. None if the key is unknown."""
    row = query_db("SELECT master_value, local_value, is_overridden "
                   "FROM managed_defaults WHERE item_key=%s", (item_key,), fetchone=True)
    if not row:
        return None
    return row["local_value"] if row["is_overridden"] else row["master_value"]


def list_managed():
    """All managed items with their effective value + override state, for the
    admin fleet panel."""
    rows = query_db("SELECT item_key, category, master_version, master_value, local_value, "
                    "is_overridden, override_version FROM managed_defaults "
                    "ORDER BY category, item_key") or []
    out = []
    for r in rows:
        d = dict(r)
        d["effective_value"] = r["local_value"] if r["is_overridden"] else r["master_value"]
        d["update_available"] = bool(r["is_overridden"]
                                     and (r["override_version"] or 0) < r["master_version"])
        out.append(d)
    return out


def fleet_status() -> dict:
    """Snapshot for the master's fleet dashboard: app version, applied bundle
    version, managed/override counts, schema health."""
    def _count(sql):
        return int((query_db(sql, fetchone=True) or {}).get("n", 0))
    return {
        "app_version": __version__,
        "deploy_mode": config.DEPLOY_MODE,
        "last_bundle_version": _latest_bundle_version(),
        "managed_count": _count("SELECT COUNT(*) AS n FROM managed_defaults"),
        "overridden_count": _count("SELECT COUNT(*) AS n FROM managed_defaults WHERE is_overridden"),
        "update_available_count": _count(
            "SELECT COUNT(*) AS n FROM managed_defaults "
            "WHERE is_overridden AND COALESCE(override_version,0) < master_version"),
        "config": config.summary(),
    }
