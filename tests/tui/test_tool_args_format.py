"""Tests for tool_args_format.py (tui-tool-panel-v2-spec.md §5.5, §12)."""

from __future__ import annotations

import pytest
from rich.text import Text

from hermes_cli.tui.tool_args_format import (
    file_args,
    shell_args,
    code_args,
    search_args,
    web_args,
    agent_args,
    generic_args,
    get_formatter,
)


# ---------------------------------------------------------------------------
# file_args
# ---------------------------------------------------------------------------


def test_file_args_path():
    rows = file_args({"path": "src/a.py"})
    assert len(rows) >= 1
    key, val = rows[0]
    assert key == "path"
    assert isinstance(val, Text)
    assert "a.py" in val.plain


def test_file_args_path_with_dir():
    rows = file_args({"path": "src/components/widget.py"})
    key, val = rows[0]
    assert "widget.py" in val.plain
    assert "src/components/" in val.plain


def test_file_args_line_range():
    rows = file_args({"path": "foo.py", "line_range": "10-20"})
    keys = [r[0] for r in rows]
    assert "range" in keys


def test_file_args_large_content():
    rows = file_args({"path": "x.py", "content": "x" * 100})
    keys = [r[0] for r in rows]
    assert "content" in keys
    content_row = next(r for r in rows if r[0] == "content")
    assert "chars" in content_row[1].plain


def test_file_args_empty():
    rows = file_args({})
    assert rows == []


# ---------------------------------------------------------------------------
# shell_args
# ---------------------------------------------------------------------------


def test_shell_args_command():
    rows = shell_args({"command": "ls -la"})
    assert rows[0][0] == "command"
    assert "ls -la" in rows[0][1].plain


def test_shell_args_with_cwd():
    rows = shell_args({"command": "make", "cwd": "/tmp/project"})
    keys = [r[0] for r in rows]
    assert "cwd" in keys


def test_shell_args_with_timeout():
    rows = shell_args({"command": "sleep 5", "timeout": 30})
    keys = [r[0] for r in rows]
    assert "timeout" in keys
    t_row = next(r for r in rows if r[0] == "timeout")
    assert "30s" in t_row[1].plain


def test_shell_args_long_command_truncated():
    long_cmd = "x" * 2000
    rows = shell_args({"command": long_cmd})
    cmd_val = rows[0][1].plain
    assert len(cmd_val) <= 1850  # 1800 + " … (+N chars)" prefix
    assert "chars" in cmd_val


# ---------------------------------------------------------------------------
# code_args
# ---------------------------------------------------------------------------


def test_code_args_line_count():
    rows = code_args({"code": "line1\nline2\nline3"})
    assert rows[0][0] == "code"
    assert "3 lines" in rows[0][1].plain


def test_code_args_empty():
    rows = code_args({"code": ""})
    assert "0 lines" in rows[0][1].plain


# ---------------------------------------------------------------------------
# search_args
# ---------------------------------------------------------------------------


def test_search_args_query():
    rows = search_args({"query": "def foo"})
    assert rows[0][0] == "query"
    assert "def foo" in rows[0][1].plain


def test_search_args_pattern():
    rows = search_args({"pattern": "*.py"})
    assert "*.py" in rows[0][1].plain


def test_search_args_with_path():
    rows = search_args({"query": "bar", "path": "src/"})
    keys = [r[0] for r in rows]
    assert "path" in keys


# ---------------------------------------------------------------------------
# web_args
# ---------------------------------------------------------------------------


def test_web_args_url():
    rows = web_args({"url": "https://example.com/page"})
    assert rows[0][0] == "url"
    assert "example.com" in rows[0][1].plain


# ---------------------------------------------------------------------------
# agent_args
# ---------------------------------------------------------------------------


def test_agent_args_thought():
    rows = agent_args({"thought": "I should check the API first"})
    assert rows[0][0] == "thought"
    assert "API" in rows[0][1].plain


def test_agent_args_empty():
    rows = agent_args({})
    assert rows == []


# ---------------------------------------------------------------------------
# generic_args
# ---------------------------------------------------------------------------


def test_generic_args_shows_first_5():
    args = {f"key{i}": f"val{i}" for i in range(10)}
    rows = generic_args(args)
    assert len(rows) == 5


def test_generic_args_long_value_truncated():
    rows = generic_args({"key": "x" * 200})
    val = rows[0][1].plain
    assert len(val) <= 82  # 80 + "…"


# ---------------------------------------------------------------------------
# get_formatter registry
# ---------------------------------------------------------------------------


def test_get_formatter_known():
    fn = get_formatter("file_args")
    assert fn is file_args


def test_get_formatter_unknown_fallback():
    fn = get_formatter("nonexistent_formatter")
    assert fn is generic_args
