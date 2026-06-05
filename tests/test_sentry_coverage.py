"""Task 092 — regression guard: every HANDLED 5xx must report to Sentry.

Flask's Sentry integration only auto-captures UNHANDLED exceptions. A route that
catches an exception and RETURNS a 5xx (`return jsonify({"error": ...}), 500`) is
invisible to Sentry unless it explicitly calls `capture_exc(e, ...)` (core.py) or
`sentry_sdk.capture_exception(e)`. This is a pure-AST static check (no DB / app
import needed): it scans the route-bearing modules and fails if any `except`
handler can return a 5xx without a capture call somewhere in that handler.

Covers the dominant pattern (`return <body>, <5xx-int>`). It will NOT catch a 5xx
returned via a non-literal helper (`return _err(500)`) — those are rare here; add
a capture by hand if you introduce one.
"""
import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Route-bearing / handler modules. Background workers (messaging.py, stripe_sync.py)
# already capture; the visitor/admin SSE + automations are covered inline.
SCAN_FILES = (
    [os.path.join(ROOT, "app.py"), os.path.join(ROOT, "automations.py")]
    + sorted(glob.glob(os.path.join(ROOT, "admin", "*.py")))
)

_CAPTURE_NAMES = {"capture_exc"}            # core.py helper
_CAPTURE_ATTRS = {"capture_exception"}      # sentry_sdk.capture_exception


def _returns_5xx(handler):
    """True if this except handler's body can `return <x>, <int 500-599>`."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) and len(n.value.elts) >= 2:
            last = n.value.elts[-1]
            if isinstance(last, ast.Constant) and isinstance(last.value, int) and 500 <= last.value <= 599:
                return True
    return False


def _has_capture(handler):
    """True if the handler's body calls capture_exc(...) / *.capture_exception(...)."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in _CAPTURE_NAMES:
                return True
            if isinstance(f, ast.Attribute) and f.attr in _CAPTURE_ATTRS:
                return True
    return False


def _violations():
    out = []
    for path in SCAN_FILES:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for handler in ast.walk(tree):
            if isinstance(handler, ast.ExceptHandler) and _returns_5xx(handler) and not _has_capture(handler):
                out.append(f"{os.path.relpath(path, ROOT)}:{handler.lineno}")
    return out


def test_handled_5xx_responses_report_to_sentry():
    bad = _violations()
    assert not bad, (
        "Handled 5xx responses with no Sentry capture (add `capture_exc(e, \"where\")` "
        "as the first line of the except block) — %d site(s):\n  %s"
        % (len(bad), "\n  ".join(bad))
    )
