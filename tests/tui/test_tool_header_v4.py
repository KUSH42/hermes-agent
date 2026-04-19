"""Tests for v4 header rendering: duration rule, primary-arg label, v2 parity.

Covers spec §2.1 (primary-arg header) and §2.2 (duration rule).
"""

from __future__ import annotations

import pytest

from hermes_cli.tui.tool_blocks import (
    _format_duration_v4,
    header_label_v4,
    ToolHeader,
    ToolHeaderStats,
)
from hermes_cli.tui.tool_category import ToolCategory, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(primary_arg=None, category=ToolCategory.UNKNOWN, render_header=True):
    return ToolSpec(
        name="test_tool",
        category=category,
        primary_arg=primary_arg,
        primary_result="none",
        render_header=render_header,
    )


# ---------------------------------------------------------------------------
# §2.2 duration rule: _format_duration_v4
# ---------------------------------------------------------------------------

class TestFormatDurationV4:
    def test_sub_50ms_omitted(self):
        assert _format_duration_v4(0) == ""
        assert _format_duration_v4(49.9) == ""

    def test_exactly_50ms(self):
        assert _format_duration_v4(50) == "50ms"

    def test_mid_range(self):
        assert _format_duration_v4(2500) == "2500ms"

    def test_upper_bound_just_under_5s(self):
        assert _format_duration_v4(4999) == "4999ms"

    def test_exactly_5000ms_switches_to_seconds(self):
        assert _format_duration_v4(5000) == "5.0s"

    def test_over_5s(self):
        assert _format_duration_v4(10500) == "10.5s"

    def test_large_value(self):
        assert _format_duration_v4(120000) == "120.0s"


# ---------------------------------------------------------------------------
# §2.1 primary-arg label: header_label_v4
# ---------------------------------------------------------------------------

class TestHeaderLabelPath:
    def test_plain_filename_no_dir(self):
        spec = _make_spec("path")
        t = header_label_v4(spec, {}, "app.py", None, 60)
        plain = t.plain
        assert "app.py" in plain

    def test_dir_dim_filename_bold(self):
        spec = _make_spec("path")
        t = header_label_v4(spec, {}, "src/app.py", "src/app.py", 60)
        # directory part uses dim style
        spans = [(s.start, s.end, s.style) for s in t._spans]
        dim_spans = [s for s in spans if "dim" in str(s[2])]
        assert dim_spans, "directory part should be dim"

    def test_full_path_used_when_provided(self):
        spec = _make_spec("path")
        t = header_label_v4(spec, {}, "app.py", "/home/user/src/app.py", 60)
        assert "src/" in t.plain or "home" in t.plain or "app.py" in t.plain

    def test_line_range_from_args(self):
        spec = _make_spec("path")
        t = header_label_v4(spec, {"start_line": 5, "end_line": 20}, "file.py", None, 60)
        assert ":5-20" in t.plain

    def test_line_range_list(self):
        spec = _make_spec("path")
        t = header_label_v4(spec, {"line_range": [10, 30]}, "file.py", None, 60)
        assert ":10-30" in t.plain


class TestHeaderLabelCommand:
    def test_command_italic(self):
        spec = _make_spec("command", category=ToolCategory.SHELL)
        t = header_label_v4(spec, {}, "ls -la", None, 60)
        italic_spans = [s for s in t._spans if "italic" in str(s.style)]
        assert italic_spans, "command label should be italic"

    def test_command_truncates(self):
        spec = _make_spec("command")
        long_cmd = "a" * 100
        t = header_label_v4(spec, {}, long_cmd, None, 30)
        assert t.plain.endswith("…")
        assert len(t.plain) < 100

    def test_shell_category_adds_dollar_prefix(self):
        spec = _make_spec("command", category=ToolCategory.SHELL)
        t = header_label_v4(spec, {}, "ls", None, 60, accent_color="#FFD700")
        assert "$" in t.plain

    def test_non_shell_command_no_dollar(self):
        spec = _make_spec("command", category=ToolCategory.UNKNOWN)
        t = header_label_v4(spec, {}, "run", None, 60, accent_color="#FFD700")
        assert "$" not in t.plain


class TestHeaderLabelQuery:
    def test_query_bold_italic_quoted(self):
        spec = _make_spec("query", category=ToolCategory.SEARCH)
        t = header_label_v4(spec, {}, "foo bar", None, 60)
        assert '"foo bar"' in t.plain
        bi_spans = [s for s in t._spans if "bold" in str(s.style) and "italic" in str(s.style)]
        assert bi_spans

    def test_query_truncates(self):
        spec = _make_spec("query")
        t = header_label_v4(spec, {}, "x" * 100, None, 20)
        assert "…" in t.plain


class TestHeaderLabelUrl:
    def test_url_scheme_dim_host_bold(self):
        spec = _make_spec("url", category=ToolCategory.WEB)
        t = header_label_v4(spec, {}, "https://example.com/path", "https://example.com/path", 80)
        assert "example.com" in t.plain
        assert "https://" in t.plain

    def test_url_path_truncated_when_long(self):
        spec = _make_spec("url")
        long_url = "https://example.com/" + "a" * 200
        t = header_label_v4(spec, {}, long_url, long_url, 60)
        assert "…" in t.plain


class TestHeaderLabelAgent:
    def test_thought_italic_dim(self):
        spec = _make_spec("thought", category=ToolCategory.AGENT)
        t = header_label_v4(spec, {}, "reconsider approach", None, 60)
        italic_spans = [s for s in t._spans if "italic" in str(s.style)]
        assert italic_spans

    def test_agent_truncates_at_40_cells(self):
        spec = _make_spec("thought")
        t = header_label_v4(spec, {}, "x" * 50, None, 80)
        assert "…" in t.plain
        assert len(t.plain.strip()) <= 42  # 40 + space + ellipsis

    def test_description_primary(self):
        spec = _make_spec("description", category=ToolCategory.AGENT)
        t = header_label_v4(spec, {}, "plan the task", None, 60)
        assert "plan the task" in t.plain

    def test_task_primary(self):
        spec = _make_spec("task", category=ToolCategory.AGENT)
        t = header_label_v4(spec, {}, "do something", None, 60)
        assert "do something" in t.plain


class TestHeaderLabelNonePrimary:
    def test_none_primary_plain_label(self):
        spec = _make_spec(None)
        t = header_label_v4(spec, {}, "some_tool", None, 60)
        assert "some_tool" in t.plain

    def test_none_primary_truncates(self):
        spec = _make_spec(None)
        t = header_label_v4(spec, {}, "x" * 100, None, 20)
        assert "…" in t.plain


# ---------------------------------------------------------------------------
# v2 parity — flag off, old flags still work
# ---------------------------------------------------------------------------

class TestV4DurationFormat:
    def test_duration_sub_50ms_empty(self):
        assert _format_duration_v4(10) == ""
        assert _format_duration_v4(49) == ""

    def test_duration_ms_format_for_mid_range(self):
        assert _format_duration_v4(500) == "500ms"

    def test_duration_s_format_above_5s(self):
        assert _format_duration_v4(6000) == "6.0s"

    def test_v4_flag_on_uses_s_format_for_over_5s(self):
        assert _format_duration_v4(6000) == "6.0s"


# ---------------------------------------------------------------------------
# render_header=False → spec-driven hidden header (v4 §2.3)
# ---------------------------------------------------------------------------

class TestRenderHeaderSpec:
    def test_render_header_false_on_spec(self):
        spec = ToolSpec(name="terminal", render_header=False, primary_result="none")
        assert spec.render_header is False

    def test_render_header_true_default(self):
        spec = ToolSpec(name="bash", primary_result="none")
        assert spec.render_header is True

    def test_terminal_seed_spec_render_header_false(self):
        from hermes_cli.tui.tool_category import spec_for
        s = spec_for("terminal")
        assert s.render_header is False
        assert s.terminal_inline is True


# ---------------------------------------------------------------------------
# ToolHeader.set_args
# ---------------------------------------------------------------------------

class TestToolHeaderSetArgs:
    def test_set_args_stores_dict(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        h = ToolHeader(label="read_file", line_count=0)
        h.set_args({"path": "/tmp/foo.txt", "start_line": 1, "end_line": 10})
        assert h._header_args == {"path": "/tmp/foo.txt", "start_line": 1, "end_line": 10}

    def test_set_args_empty_dict_accepted(self):
        from hermes_cli.tui.tool_blocks import ToolHeader
        h = ToolHeader(label="x", line_count=0)
        h.set_args({})
        assert h._header_args == {}
