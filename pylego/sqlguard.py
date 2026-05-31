"""pylego.sqlguard — read-only SQL validation, ported from @altay/sql-guardrail.

A dependency-free validator that a SQL string is a SINGLE read-only
SELECT/WITH statement. The monolith's admin SQL tool already enforces this
(plus a read-only transaction at execution time); this is an additional,
self-contained gate that can be layered ON TOP as defense-in-depth.

CONTRACT: `check(sql)` returns `(ok: bool, reason: str)`. It only ever REJECTS
(returns ok=False) — wiring it as an extra gate can make the SQL tool stricter
but never more permissive, so enabling it can't open a hole. Total (never
raises); on an internal error it returns ok=False with a reason (fail-CLOSED,
because this is a safety gate — the caller may choose to fall back to its own
existing check).
"""

from __future__ import annotations

import re
from typing import Tuple

# Write / DDL / side-effecting keywords that must never appear.
_FORBIDDEN = re.compile(
    r"(?is)\b(INSERT|UPDATE|DELETE|MERGE|UPSERT|TRUNCATE|DROP|CREATE|ALTER|"
    r"GRANT|REVOKE|COMMENT|VACUUM|ANALYZE|REINDEX|CLUSTER|REFRESH|LOCK|"
    r"COPY|CALL|DO|EXECUTE|PREPARE|DEALLOCATE|SET|RESET|BEGIN|COMMIT|"
    r"ROLLBACK|SAVEPOINT|LISTEN|NOTIFY|SECURITY\s+LABEL|INTO)\b")

# A leading SELECT or WITH (after stripping comments/whitespace) is required.
_LEADING = re.compile(r"(?is)^\s*(SELECT|WITH)\b")

# Strip SQL comments so a forbidden keyword can't hide behind `-- ...` / /* */.
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_comments(sql: str) -> str:
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql))


def check(sql: str) -> Tuple[bool, str]:
    """Return (ok, reason). ok=True only for a single read-only SELECT/WITH."""
    try:
        if not sql or not isinstance(sql, str):
            return False, "empty SQL"
        s = _strip_comments(sql).strip().rstrip(";").strip()
        if not s:
            return False, "empty SQL"
        if ";" in s:
            return False, "multiple statements are not allowed"
        if not _LEADING.match(s):
            return False, "only SELECT or WITH queries are allowed"
        m = _FORBIDDEN.search(s)
        if m:
            return False, f"forbidden keyword: {m.group(1).upper()}"
        return True, ""
    except Exception as e:  # fail CLOSED — never green-light on our own bug.
        return False, f"sqlguard error: {type(e).__name__}"


def is_read_only(sql: str) -> bool:
    return check(sql)[0]
