"""Tests for tool_result_parse.py (tui-tool-panel-v2-spec.md §5.6, §12)."""

from __future__ import annotations

import pytest

from hermes_cli.tui.tool_result_parse import (
    ResultSummary,
    shell_result,
    code_result,
    file_result,
    search_result,
    web_result,
    agent_result,
    generic_result,
    get_parser,
)


# ---------------------------------------------------------------------------
# ResultSummary dataclass
# ---------------------------------------------------------------------------


def test_result_summary_defaults():
    rs = ResultSummary()
    assert rs.exit_code is None
    assert rs.stat_badges == []
    assert rs.stderr_tail == ""
    assert rs.retry_hint is None
    assert rs.is_error is False


# ---------------------------------------------------------------------------
# shell_result
# ---------------------------------------------------------------------------


def test_shell_result_success():
    rs = shell_result("Done.\nexit code: 0")
    assert rs.exit_code == 0
    assert rs.is_error is False


def test_shell_result_error_exit_code():
    rs = shell_result("make: *** Error\nexit code: 2")
    assert rs.exit_code == 2
    assert rs.is_error is True


def test_shell_result_error_stderr_tail():
    rs = shell_result("something\nfailed with code\nexit: 1")
    assert rs.is_error is True
    assert rs.stderr_tail  # last nonempty line


def test_shell_result_no_exit_code():
    rs = shell_result("output without exit marker")
    assert rs.exit_code is None
    assert rs.is_error is False


# ---------------------------------------------------------------------------
# file_result
# ---------------------------------------------------------------------------


def test_file_result_diff_badges():
    rs = file_result("+10 lines added, -3 lines removed")
    assert any(b.startswith("+") for b in rs.stat_badges)
    assert any(b.startswith("-") for b in rs.stat_badges)


def test_file_result_line_count_badge():
    rs = file_result("line1\nline2\nline3\nline4")
    # Should have some badge
    assert rs.stat_badges


def test_file_result_error():
    rs = file_result("Error: file not found")
    assert rs.is_error is True


def test_file_result_success():
    rs = file_result("File written successfully")
    assert rs.is_error is False


# ---------------------------------------------------------------------------
# search_result
# ---------------------------------------------------------------------------


def test_search_result_matches():
    result = "src/a.py:10: def foo()\nsrc/b.py:20: def bar()"
    rs = search_result(result)
    assert any("match" in b for b in rs.stat_badges)


def test_search_result_empty():
    rs = search_result("")
    assert rs.stat_badges == [] or all(b == "0 matches" for b in rs.stat_badges)


# ---------------------------------------------------------------------------
# web_result
# ---------------------------------------------------------------------------


def test_web_result_http_status():
    rs = web_result("HTTP 200 OK\nContent: ...")
    assert any("200" in b for b in rs.stat_badges)


def test_web_result_error_status():
    rs = web_result("HTTP 404 Not Found")
    assert rs.is_error is True


def test_web_result_size_badge():
    rs = web_result("Content-Length: 320KB received")
    assert any("B" in b.upper() for b in rs.stat_badges)


# ---------------------------------------------------------------------------
# agent_result / generic_result
# ---------------------------------------------------------------------------


def test_agent_result_always_ok():
    rs = agent_result("Thought: analyzing the problem...")
    assert rs.is_error is False
    assert rs.stat_badges == []


def test_generic_result_error_keyword():
    rs = generic_result("Error: something broke")
    assert rs.is_error is True


def test_generic_result_exception():
    rs = generic_result("Exception: NullPointerException")
    assert rs.is_error is True


def test_generic_result_success():
    rs = generic_result("Result: 42")
    assert rs.is_error is False


# ---------------------------------------------------------------------------
# stat_badges format validation
# ---------------------------------------------------------------------------

import re

_VALID_BADGE_PATTERNS = [
    re.compile(r"^[+-]\d+$"),                      # +N / -N
    re.compile(r"^\d{3} [A-Z][A-Z]+$"),             # HTTP status
    re.compile(r"^\d+(?:\.\d+)?[KMGT]?B$", re.I),   # size
    re.compile(r"^\d+ (?:files?|lines?|rows?|matches?)$"),  # count
]


def _is_valid_badge(badge: str) -> bool:
    return any(p.match(badge) for p in _VALID_BADGE_PATTERNS)


def test_stat_badges_are_valid_shapes():
    """All stat_badges from all parsers must match a recognized shape."""
    test_cases = [
        shell_result("exit code: 0"),
        file_result("+5 lines added"),
        search_result("a.py:1: x\nb.py:2: y"),
        web_result("HTTP 200 OK"),
    ]
    for rs in test_cases:
        for badge in rs.stat_badges:
            assert _is_valid_badge(badge), f"Invalid badge shape: {badge!r}"


# ---------------------------------------------------------------------------
# get_parser registry
# ---------------------------------------------------------------------------


def test_get_parser_known():
    fn = get_parser("shell_result")
    assert fn is shell_result


def test_get_parser_unknown_fallback():
    fn = get_parser("nonexistent")
    assert fn is generic_result


# ---------------------------------------------------------------------------
# search_result_v4 — web_search JSON count fix
# ---------------------------------------------------------------------------


def _make_search_ctx(raw, query="test"):
    """Build a ParseContext for web_search."""
    from hermes_cli.tui.tool_result_parse import search_result_v4, ParseContext, ToolStart, ToolComplete
    from hermes_cli.tui.tool_category import spec_for
    spec = spec_for("web_search")
    return ParseContext(
        complete=ToolComplete(name="web_search", raw_result=raw),
        start=ToolStart(name="web_search", args={"query": query}),
        spec=spec,
    )


def test_search_result_v4_json_count():
    """search_result_v4 counts data.web entries, not raw lines."""
    import json
    from hermes_cli.tui.tool_result_parse import search_result_v4

    payload = json.dumps({
        "success": True,
        "data": {
            "web": [
                {"url": "https://a.com", "title": "A", "description": "desc a"},
                {"url": "https://b.com", "title": "B", "description": "desc b"},
                {"url": "https://c.com", "title": "C", "description": "desc c"},
            ]
        }
    })
    result = search_result_v4(_make_search_ctx(payload))
    assert "3" in result.primary


def test_search_result_v4_json_count_fallback():
    """Non-JSON raw falls back to line count."""
    from hermes_cli.tui.tool_result_parse import search_result_v4

    raw = "match1\nmatch2\nmatch3\n"
    result = search_result_v4(_make_search_ctx(raw))
    assert "3" in result.primary


def test_search_result_v4_json_empty_web_array():
    """JSON with empty data.web falls back gracefully."""
    import json
    from hermes_cli.tui.tool_result_parse import search_result_v4

    payload = json.dumps({"success": True, "data": {"web": []}})
    result = search_result_v4(_make_search_ctx(payload))
    assert result is not None
