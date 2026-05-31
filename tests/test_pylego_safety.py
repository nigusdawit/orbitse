"""Tests for the pylego safety modules (task 029): redact, sqlguard,
structured, action_queue — plus the obs→redact wiring."""
import logging
import os

from pylego import redact, sqlguard, structured, action_queue as aq
from pylego import obs, config


# ---- obs → redact wiring (the one net-new wired safety win) -----------------

def test_obs_redacts_secret_in_logged_error(caplog):
    os.environ["PYLEGO_OBS_ENABLED"] = "1"
    os.environ["ADMIN_REDACT_ENABLED"] = "1"
    config.reload_config()

    def boom():
        yield {"type": "token", "content": "hi"}
        raise RuntimeError("auth failed for key sk-LEAKEDSECRET123")

    caplog.set_level(logging.INFO, logger="pylego.obs")
    seen = []
    try:
        for evt in obs.observe_admin_turn({"session_id": "s"}, boom()):
            seen.append(evt)
    except RuntimeError:
        pass
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "sk-LEAKEDSECRET123" not in blob   # secret never reaches the log
    assert "[REDACTED]" in blob


# ---- redact -----------------------------------------------------------------

def test_redact_masks_secrets_and_pii():
    assert "[REDACTED]" in redact.redact_text("key is sk-ABC123DEF456")
    assert "a@b.com" not in redact.redact_text("email a@b.com please")
    assert "[REDACTED]" in redact.redact_text("call +1 (555) 123-4567 now")
    assert "[REDACTED]" in redact.redact_text("Authorization: Bearer abcdef123456")
    assert "[REDACTED]" in redact.redact_text("api_key=supersecretvalue")


def test_redact_passthrough_and_total():
    assert redact.redact_text("nothing sensitive here") == "nothing sensitive here"
    assert redact.redact_text(None) is None
    assert redact.redact_text(123) == 123  # non-str unchanged


def test_redact_mapping_only_listed_keys():
    rec = {"error_text": "token=abc123secret", "status": "ok", "n": 5}
    out = redact.redact_mapping(rec, ["error_text"])
    assert "[REDACTED]" in out["error_text"]
    assert out["status"] == "ok" and out["n"] == 5


# ---- sqlguard ---------------------------------------------------------------

def test_sqlguard_allows_select_and_with():
    assert sqlguard.check("SELECT * FROM users")[0] is True
    assert sqlguard.check("  with t as (select 1) select * from t ")[0] is True


def test_sqlguard_rejects_writes_and_ddl():
    for bad in ["DELETE FROM users", "UPDATE users SET x=1", "DROP TABLE t",
                "INSERT INTO t VALUES (1)", "TRUNCATE t", "ALTER TABLE t ADD c int"]:
        ok, reason = sqlguard.check(bad)
        assert ok is False and reason


def test_sqlguard_rejects_multi_statement_and_comment_hiding():
    assert sqlguard.check("SELECT 1; DROP TABLE t")[0] is False
    # forbidden keyword hidden behind a comment must still be caught
    assert sqlguard.check("SELECT 1 /* */ ; DELETE FROM t")[0] is False
    assert sqlguard.check("SELECT 1 -- ok\n; DELETE FROM t")[0] is False


def test_sqlguard_rejects_empty_and_nonstring():
    assert sqlguard.check("")[0] is False
    assert sqlguard.check(None)[0] is False  # type: ignore[arg-type]


def test_sqlguard_only_ever_rejects_relative_to_a_passing_query():
    # A query that passes sqlguard is a strict subset of "looks like a SELECT".
    assert sqlguard.is_read_only("SELECT a, b FROM t WHERE a > 1")


# ---- structured -------------------------------------------------------------

def test_parse_tool_args_dict_and_json():
    assert structured.parse_tool_args({"a": 1}) == ({"a": 1}, "")
    assert structured.parse_tool_args('{"a": 1}') == ({"a": 1}, "")
    assert structured.parse_tool_args("") == ({}, "")
    assert structured.parse_tool_args(None) == ({}, "")


def test_parse_tool_args_reports_errors():
    obj, err = structured.parse_tool_args("{not json")
    assert obj is None and "JSON" in err
    obj2, err2 = structured.parse_tool_args("[1,2,3]")
    assert obj2 is None and "object" in err2.lower()


def test_run_with_repair_retries_then_succeeds():
    attempts = {"n": 0}

    def call(feedback):
        attempts["n"] += 1
        return "{bad" if attempts["n"] == 1 else '{"ok": true}'

    parsed, err = structured.run_with_repair(call, structured.parse_tool_args,
                                             max_retries=1)
    assert err == "" and parsed == {"ok": True}
    assert attempts["n"] == 2


def test_run_with_repair_gives_up_with_last_error():
    parsed, err = structured.run_with_repair(
        lambda fb: "{still bad", structured.parse_tool_args, max_retries=1)
    assert parsed is None and err


# ---- action_queue -----------------------------------------------------------

def test_transition_machine():
    assert aq.validate_transition("pending", "approved") == (True, "")
    assert aq.validate_transition("pending", "rejected")[0] is True
    # terminal states are final → blocks double-approve / re-execute
    assert aq.validate_transition("approved", "approved")[0] is False
    assert aq.validate_transition("approved", "rejected")[0] is False
    assert aq.validate_transition("rejected", "approved")[0] is False
    assert aq.validate_transition("bogus", "approved")[0] is False


def test_idempotency_key_stable_and_distinct():
    k1 = aq.idempotency_key("s1", "admin_propose_delete", {"row_id": 5, "t": "x"})
    k2 = aq.idempotency_key("s1", "admin_propose_delete", {"t": "x", "row_id": 5})
    k3 = aq.idempotency_key("s1", "admin_propose_delete", {"row_id": 6, "t": "x"})
    assert k1 == k2          # arg key order doesn't matter
    assert k1 != k3          # different args → different key
    assert len(k1) == 64     # sha256 hex
