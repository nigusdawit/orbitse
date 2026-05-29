"""Import-hygiene tests.

1. Every package module imports cleanly (no DB / network needed at import).
2. No module couples back to the legacy monolith via ``import app`` /
   ``from app import ...`` — the package is an independent copy.
3. ``create_app(init_schema=False, start_scheduler=False)`` builds an app and
   serves /healthz without a database.
"""

import os
import re
import pkgutil
import importlib

import admin_ai_platform

_APP_IMPORT_RE = re.compile(r"(?m)^\s*(from\s+app\s+import\b|import\s+app\b)")

# Modules that construct heavy clients or are entrypoints — still importable,
# but listed so the walk is explicit.
_PKG_ROOT = os.path.dirname(admin_ai_platform.__file__)


def _iter_module_names():
    for mod in pkgutil.walk_packages([_PKG_ROOT], prefix="admin_ai_platform."):
        # Skip the dev entrypoint (it has no side effects at import, but be safe)
        if mod.name.endswith(".__main__"):
            continue
        yield mod.name


def test_all_modules_import():
    for name in _iter_module_names():
        importlib.import_module(name)


def test_no_legacy_app_import():
    offenders = []
    for root, _dirs, files in os.walk(_PKG_ROOT):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            if _APP_IMPORT_RE.search(src):
                offenders.append(os.path.relpath(path, _PKG_ROOT))
    assert not offenders, f"modules import the legacy app: {offenders}"


def test_create_app_without_db():
    app = admin_ai_platform.create_app(init_schema=False, start_scheduler=False)
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "deploy_mode" in body
