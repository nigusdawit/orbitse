"""Tests for pylego.evals — the dependency-free eval runner."""
from pylego.evals import Case, Suite, run_suite
from pylego.evals.admin_ai_suite import build_suite


def test_assertions_pass_and_fail_correctly():
    suite = Suite(name="t", cases=[
        Case(name="contains_ok", input="x",
             assertions=[{"type": "contains", "value": "hello"}]),
        Case(name="contains_fail", input="x",
             assertions=[{"type": "contains", "value": "absent"}]),
        Case(name="regex_ok", input="x",
             assertions=[{"type": "regex", "value": r"\d+"}]),
        Case(name="not_contains_ok", input="x",
             assertions=[{"type": "not_contains", "value": "zzz"}]),
        Case(name="json_ok", input="x",
             assertions=[{"type": "json_schema", "required_keys": ["a"]}]),
    ])

    def runner(case: Case) -> str:
        return {
            "contains_ok": "say hello there",
            "contains_fail": "nothing here",
            "regex_ok": "answer is 42",
            "not_contains_ok": "clean output",
            "json_ok": '{"a": 1, "b": 2}',
        }[case.name]

    rep = run_suite(suite, runner)
    by = {r.name: r.passed for r in rep.results}
    assert by == {
        "contains_ok": True, "contains_fail": False, "regex_ok": True,
        "not_contains_ok": True, "json_ok": True,
    }
    assert rep.passed == 4 and rep.failed == 1 and not rep.ok


def test_llm_judge_skipped_without_judge_counts_as_pass():
    suite = Suite(name="j", cases=[
        Case(name="judged", input="x",
             assertions=[{"type": "llm_judge", "rubric": "is polite"}])])
    rep = run_suite(suite, lambda c: "hello!")
    assert rep.ok  # judge unconfigured → skipped, not a failure


def test_runner_exception_fails_only_that_case():
    suite = Suite(name="e", cases=[
        Case(name="boom", input="x", assertions=[{"type": "contains", "value": "y"}]),
        Case(name="fine", input="x", assertions=[{"type": "contains", "value": "y"}]),
    ])

    def runner(case):
        if case.name == "boom":
            raise RuntimeError("nope")
        return "y"

    rep = run_suite(suite, runner)
    by = {r.name: r.passed for r in rep.results}
    assert by == {"boom": False, "fine": True}


def test_junit_output_is_wellformed():
    rep = run_suite(
        Suite(name="x", cases=[Case(name="c", input="i",
              assertions=[{"type": "contains", "value": "z"}])]),
        lambda c: "z")
    xml = rep.to_junit()
    assert xml.startswith("<testsuite") and "</testsuite>" in xml
    assert 'name="c"' in xml


def test_seed_suite_runs_against_a_stub():
    # The seed suite must be runnable anywhere with a stub runner (no API spend).
    suite = build_suite()
    assert suite.name == "admin_ai_seed" and len(suite.cases) >= 3
    # A well-behaved answer satisfies all seed assertions: mentions a count,
    # doesn't refuse outright, and doesn't claim a destructive action happened.
    rep = run_suite(suite, lambda c: "There are 3 gallery cards. Deleting data requires your approval first.")
    assert len(rep.results) == len(suite.cases)
    assert rep.ok, [(r.name, r.assertions) for r in rep.results if not r.passed]
