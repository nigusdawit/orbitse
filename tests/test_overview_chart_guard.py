"""Regression guard for the admin chart.js stack-overflow (fix: Overview chart recursion).

The 'adminThemeColors' Chart plugin used to recolor charts by walking and mutating each
chart's RESOLVED options proxy (chart.options.scales[*].ticks/grid) inside a beforeUpdate
hook. In chart.js 4.x that proxy write recurses into Object.set →
"RangeError: Maximum call stack size exceeded", which broke EVERY admin chart (the
Overview trend was simply the first one loaded). Confirmed in-browser by bisection: a
chart with {plugins:{adminThemeColors:false}} renders; the same chart with the plugin
throws. The fix themes globally via Chart.defaults instead.

This is a browser-runtime bug and the embedded-PG suite has no headless-DOM harness, so we
pin it at the source level: (1) the theme integration must drive Chart.defaults, and
(2) no Chart plugin hook may mutate the chart.options proxy again.
"""
import os
import re

_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "public", "admin", "app-main.js",
)


def _src():
    with open(_JS, encoding="utf-8") as f:
        return f.read()


def test_chart_theming_drives_defaults():
    # the fix: global, recursion-safe theming via Chart.defaults
    src = _src()
    assert "Chart.defaults.color" in src, "chart tick/legend theming (Chart.defaults.color) missing"
    assert "Chart.defaults.borderColor" in src, "chart grid theming (Chart.defaults.borderColor) missing"


def test_no_chart_update_hook_mutates_options_proxy():
    # the anti-pattern that recursed: a Chart plugin update hook touching chart.options.
    # Scan each before/after-Update|Render hook body and assert it never references
    # chart.options (mutating that resolved proxy is what blew the stack in chart.js 4.x).
    src = _src()
    hooks = list(re.finditer(r"(before|after)(Update|Render|Layout|Draw)\s*:\s*function\s*\([^)]*\)\s*\{", src))
    for m in hooks:
        body = src[m.end():m.end() + 600]
        assert "chart.options" not in body, (
            "a Chart.js plugin update hook mutates chart.options — that resolved-proxy "
            "write recurses in chart.js 4.x (see the Overview chart stack-overflow fix); "
            "theme via Chart.defaults instead"
        )
