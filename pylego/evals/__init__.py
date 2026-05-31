"""pylego.evals — a tiny, dependency-free LLM eval runner.

Ported from @altay/eval-harness (+ a hook for @altay/ragas-runner). Lets us pin
the Admin AI's behavior with test cases and catch regressions as we change the
agent. Assertion vocabulary mirrors the TS package (`regex`, `json_schema`,
`llm_judge`) so the two stay conceptually interchangeable.

Decoupled from any specific model: `run_suite(suite, runner)` calls `runner(case)`
— a callable you supply that returns the agent's output text for a case. In CI
or unit tests you can pass a stub/recorded runner (no API spend); against the
live agent you pass a real runner. This is what makes evals safe to run anywhere.

This module is observation-only: it NEVER touches the admin chat hot path. It's
invoked manually or from CI, not from request handling.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Case:
    """One eval case. `assertions` is a list of dicts, each {type, ...}."""
    name: str
    input: str
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Suite:
    name: str
    cases: List[Case] = field(default_factory=list)


@dataclass
class AssertionResult:
    type: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    name: str
    passed: bool
    output: str
    assertions: List[AssertionResult] = field(default_factory=list)
    error: str = ""


@dataclass
class SuiteReport:
    suite: str
    results: List[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_junit(self) -> str:
        """Minimal JUnit XML so CI can render pass/fail per case."""
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))
        out = [f'<testsuite name="{esc(self.suite)}" tests="{len(self.results)}" '
               f'failures="{self.failed}">']
        for r in self.results:
            out.append(f'  <testcase name="{esc(r.name)}">')
            if not r.passed:
                fails = "; ".join(f"{a.type}: {a.detail}"
                                  for a in r.assertions if not a.passed) or r.error
                out.append(f'    <failure message="{esc(fails)}"></failure>')
            out.append("  </testcase>")
        out.append("</testsuite>")
        return "\n".join(out)


# ---- Built-in assertion evaluators -----------------------------------------
# Each returns an AssertionResult. `llm_judge` needs a judge callable, supplied
# via run_suite(..., judge=...); without one it is skipped (reported as passed
# with a note) so suites stay runnable in CI with zero API spend.

def _assert_contains(output: str, spec: Dict[str, Any]) -> AssertionResult:
    needle = str(spec.get("value", ""))
    ci = bool(spec.get("ignore_case", True))
    hay = output.lower() if ci else output
    nee = needle.lower() if ci else needle
    ok = nee in hay
    return AssertionResult("contains", ok, "" if ok else f"missing {needle!r}")


def _assert_not_contains(output: str, spec: Dict[str, Any]) -> AssertionResult:
    needle = str(spec.get("value", ""))
    ci = bool(spec.get("ignore_case", True))
    hay = output.lower() if ci else output
    nee = needle.lower() if ci else needle
    ok = nee not in hay
    return AssertionResult("not_contains", ok, "" if ok else f"found {needle!r}")


def _assert_regex(output: str, spec: Dict[str, Any]) -> AssertionResult:
    pat = str(spec.get("value", ""))
    ok = re.search(pat, output) is not None
    return AssertionResult("regex", ok, "" if ok else f"no match for /{pat}/")


def _assert_json_schema(output: str, spec: Dict[str, Any]) -> AssertionResult:
    """Lightweight check: output parses as JSON and contains the required keys.
    (Full JSON-Schema validation is intentionally out of scope to avoid a dep;
    required-keys covers the common agent-output case.)"""
    required = spec.get("required_keys") or []
    try:
        obj = json.loads(output)
    except Exception as e:
        return AssertionResult("json_schema", False, f"not JSON: {e}")
    missing = [k for k in required if k not in obj]
    ok = not missing
    return AssertionResult("json_schema", ok,
                           "" if ok else f"missing keys {missing}")


def _assert_llm_judge(output: str, spec: Dict[str, Any],
                      judge: Optional[Callable[[str, str], bool]]) -> AssertionResult:
    rubric = str(spec.get("rubric", ""))
    if judge is None:
        return AssertionResult("llm_judge", True, "skipped (no judge configured)")
    try:
        ok = bool(judge(output, rubric))
        return AssertionResult("llm_judge", ok, "" if ok else "judge rejected")
    except Exception as e:
        return AssertionResult("llm_judge", False, f"judge error: {e}")


def _eval_assertion(output: str, spec: Dict[str, Any],
                    judge: Optional[Callable[[str, str], bool]]) -> AssertionResult:
    t = spec.get("type")
    if t == "contains":
        return _assert_contains(output, spec)
    if t == "not_contains":
        return _assert_not_contains(output, spec)
    if t == "regex":
        return _assert_regex(output, spec)
    if t == "json_schema":
        return _assert_json_schema(output, spec)
    if t == "llm_judge":
        return _assert_llm_judge(output, spec, judge)
    return AssertionResult(str(t), False, f"unknown assertion type {t!r}")


def run_suite(suite: Suite,
              runner: Callable[[Case], str],
              judge: Optional[Callable[[str, str], bool]] = None) -> SuiteReport:
    """Run every case through `runner` and evaluate its assertions.

    `runner(case) -> output_text`. Any runner exception fails just that case
    (the suite keeps going), so one flaky case can't abort the run.
    """
    report = SuiteReport(suite=suite.name)
    for case in suite.cases:
        try:
            output = runner(case)
        except Exception as e:
            report.results.append(CaseResult(
                name=case.name, passed=False, output="",
                error=f"runner error: {type(e).__name__}: {e}"))
            continue
        ares = [_eval_assertion(output, a, judge) for a in case.assertions]
        report.results.append(CaseResult(
            name=case.name,
            passed=all(a.passed for a in ares),
            output=output,
            assertions=ares,
        ))
    return report
