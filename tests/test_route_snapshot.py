"""Route-table snapshot — the safety net for the app.py blueprint extraction
(task 077). Captures the full URL surface (path + HTTP methods) as a committed
baseline and asserts it never changes as routes move from the global `app` into
Flask blueprints.

WHY methods+path, not endpoint name: when a route moves into a blueprint its
endpoint gains a `<bp>.` prefix (e.g. `serve_index` -> `public.serve_index`).
That's expected and fine. What must NEVER change is the externally-observable
surface — the URL rule and its methods. So we compare on `(rule, methods)`.

Baseline file: tests/routes_baseline.txt (one `METHODS RULE` line per route,
sorted). Regenerate intentionally ONLY when you deliberately add/remove a route:
delete the file and re-run under the embedded-PG harness to recapture.
"""
import os

import app


def _live_routes():
    """Sorted 'METHODS RULE' lines for every URL rule (HEAD/OPTIONS dropped —
    Flask auto-adds those, so they're noise for a stability check)."""
    out = []
    for r in app.app.url_map.iter_rules():
        methods = ",".join(sorted((r.methods or set()) - {"HEAD", "OPTIONS"}))
        out.append(f"{methods} {r.rule}")
    return sorted(out)


_BASELINE = os.path.join(os.path.dirname(__file__), "routes_baseline.txt")


def test_route_table_matches_baseline():
    assert os.path.exists(_BASELINE), (
        "tests/routes_baseline.txt missing — generate it once from the current "
        "app under the embedded-PG harness before relying on this gate."
    )
    baseline = set(l for l in open(_BASELINE, encoding="utf-8").read().splitlines() if l.strip())
    live = set(_live_routes())
    dropped = sorted(baseline - live)
    added = sorted(live - baseline)
    msg = ""
    if dropped:
        msg += "\nROUTES DROPPED/CHANGED (in baseline, not live):\n  " + "\n  ".join(dropped)
    if added:
        msg += "\nROUTES ADDED (live, not in baseline):\n  " + "\n  ".join(added)
    assert not dropped and not added, "Route table changed vs baseline." + msg
