"""Error taxonomy — closed enum and deterministic classifier for ERR transitions."""
from __future__ import annotations

import re
from enum import Enum


class ErrorCategory(str, Enum):
    ENOENT      = "ENOENT"
    EACCES      = "EACCES"
    ENOTDIR     = "ENOTDIR"      # not a directory — user-fixable via edit_args
    EINVAL      = "EINVAL"       # invalid argument / unrecognized option
    ENETUNREACH = "ENETUNREACH"
    SIGNAL      = "signal"
    USAGE       = "usage"
    RUNTIME     = "runtime"
    TIMEOUT     = "timeout"
    UNKNOWN     = "error"


STDERR_TAIL_ROWS: int = 12

_STDERR_RULES: tuple[tuple[re.Pattern[str], ErrorCategory], ...] = (
    (re.compile(r"fatal: ambiguous argument", re.I), ErrorCategory.ENOENT),
    (re.compile(r"(?:command )?not found",    re.I), ErrorCategory.ENOENT),
    (re.compile(r"permission denied",         re.I), ErrorCategory.EACCES),
    (re.compile(r"not a directory",           re.I), ErrorCategory.ENOTDIR),
    (re.compile(r"invalid argument",          re.I), ErrorCategory.EINVAL),
    (re.compile(r"unrecognized option",       re.I), ErrorCategory.EINVAL),
    (re.compile(r"connection refused",        re.I), ErrorCategory.ENETUNREACH),
    (re.compile(r"timed out|timeout",         re.I), ErrorCategory.TIMEOUT),
)


def classify_error(stderr: str | None, exit_code: int | None) -> ErrorCategory:
    """Three-stage resolver: stderr-regex → exit-code class → UNKNOWN."""
    if stderr:
        for pat, cat in _STDERR_RULES:
            if pat.search(stderr):
                return cat
    if exit_code is not None:
        if exit_code < 0:
            return ErrorCategory.SIGNAL
        if exit_code in (2, 64):
            return ErrorCategory.USAGE
        if exit_code != 0:
            return ErrorCategory.RUNTIME
    return ErrorCategory.UNKNOWN


def split_stderr_tail(stderr: str | None, *, rows: int = STDERR_TAIL_ROWS) -> list[str]:
    """Return last `rows` non-empty lines from stderr."""
    if not stderr:
        return []
    lines = [line for line in stderr.splitlines() if line.strip()]
    return lines[-rows:]
