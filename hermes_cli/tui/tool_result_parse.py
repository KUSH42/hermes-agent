"""Result parsers and ResultSummary dataclass (tui-tool-panel-v2-spec.md §5.6).

Pure functions: take raw tool-output string, return ResultSummary.
Each parser is keyed by CategoryDefaults.result_parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# ResultSummary
# ---------------------------------------------------------------------------


@dataclass
class ResultSummary:
    """Normalized tool-result metadata for FooterPane rendering.

    All fields are optional — parsers populate what they can.
    FooterPane only renders non-None / non-empty fields.
    """

    exit_code: int | None = None
    stat_badges: list[str] = field(default_factory=list)
    stderr_tail: str = ""
    retry_hint: str | None = None
    is_error: bool = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_EXIT_RE = re.compile(r"exit(?:\s+code)?[:\s]+(\d+)", re.IGNORECASE)
_DIFF_PLUS_RE = re.compile(r"\+(\d+)")
_DIFF_MINUS_RE = re.compile(r"(?<!\+)-(\d+)")
_HTTP_STATUS_RE = re.compile(r"\b([45]\d\d)\b")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]?B)\b", re.IGNORECASE)


def _extract_exit_code(result: str) -> int | None:
    m = _EXIT_RE.search(result[:500])
    return int(m.group(1)) if m else None


def _last_nonempty_line(result: str, max_chars: int = 80) -> str:
    for line in reversed(result.strip().splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:max_chars]
    return ""


# ---------------------------------------------------------------------------
# Per-category parsers
# ---------------------------------------------------------------------------


def shell_result(result: str) -> ResultSummary:
    """Parser for SHELL category (terminal, bash)."""
    exit_code = _extract_exit_code(result)
    is_error = exit_code is not None and exit_code != 0
    stderr_tail = _last_nonempty_line(result) if is_error else ""
    return ResultSummary(
        exit_code=exit_code,
        stat_badges=[],
        stderr_tail=stderr_tail,
        is_error=is_error,
    )


def code_result(result: str) -> ResultSummary:
    """Parser for CODE category (execute_code)."""
    return shell_result(result)


def file_result(result: str) -> ResultSummary:
    """Parser for FILE category (read_file, write_file, patch, etc.)."""
    badges: list[str] = []
    plus_m = _DIFF_PLUS_RE.search(result)
    minus_m = _DIFF_MINUS_RE.search(result)
    if plus_m:
        badges.append(f"+{plus_m.group(1)}")
    if minus_m:
        badges.append(f"-{minus_m.group(1)}")
    lines = [l for l in result.strip().splitlines() if l.strip()]
    if not badges and lines:
        badges.append(f"{len(lines)} lines")
    is_error = "error" in result.lower()[:200] or "failed" in result.lower()[:200]
    return ResultSummary(stat_badges=badges, is_error=is_error)


def search_result(result: str) -> ResultSummary:
    """Parser for SEARCH category (web_search, grep, glob)."""
    lines = [l for l in result.strip().splitlines() if l.strip()]
    count = len(lines)
    badges = [f"{count} matches"] if count else []
    return ResultSummary(stat_badges=badges)


def web_result(result: str) -> ResultSummary:
    """Parser for WEB category (web_extract, fetch, http)."""
    badges: list[str] = []
    head = result[:300]
    # HTTP status badge
    status_m = re.search(r"\b(\d{3})\s+([A-Z][A-Z]+)\b", head)
    if status_m:
        badges.append(f"{status_m.group(1)} {status_m.group(2)}")
    # Size badge
    size_m = _SIZE_RE.search(head)
    if size_m:
        badges.append(f"{size_m.group(1)}{size_m.group(2).upper()}")
    is_error = bool(_HTTP_STATUS_RE.search(head))
    return ResultSummary(stat_badges=badges, is_error=is_error)


def agent_result(result: str) -> ResultSummary:
    """Parser for AGENT category (think, plan, delegate)."""
    return ResultSummary()


def generic_result(result: str) -> ResultSummary:
    """Fallback parser for UNKNOWN category."""
    is_error = (
        "error" in result.lower()[:200]
        or "exception" in result.lower()[:200]
        or "traceback" in result.lower()[:200]
    )
    return ResultSummary(is_error=is_error)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_PARSERS: dict[str, object] = {
    "shell_result":   shell_result,
    "code_result":    code_result,
    "file_result":    file_result,
    "search_result":  search_result,
    "web_result":     web_result,
    "agent_result":   agent_result,
    "generic_result": generic_result,
}


def get_parser(name: str):
    """Return parser function by name; falls back to generic_result."""
    return _PARSERS.get(name, generic_result)
