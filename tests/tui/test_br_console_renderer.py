"""Tests for BrowserConsoleRenderer (spec BR-CON-1/2/3)."""
from __future__ import annotations

import json
import types

import pytest

from hermes_cli.tui.tool_category import spec_for, ToolCategory
from hermes_cli.tui.body_renderers.browser_console import BrowserConsoleRenderer


def _payload(tool_name: str, output_raw: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(tool_name=tool_name, output_raw=output_raw)


def _make_renderer(tool_name: str, output_raw: str) -> BrowserConsoleRenderer:
    return BrowserConsoleRenderer(payload=_payload(tool_name, output_raw))


def _raw(console_messages=None, js_errors=None, **extra) -> str:
    data: dict = {}
    if console_messages is not None:
        data["console_messages"] = console_messages
    if js_errors is not None:
        data["js_errors"] = js_errors
    data.update(extra)
    return json.dumps(data)


class TestCategoryRegistration:
    """BR-CON-1"""

    def test_console_categorises_as_web(self):
        assert spec_for("browser_console").category == ToolCategory.WEB


class TestBrowserConsoleRenderer:
    """BR-CON-2"""

    def test_log_entries_rendered_with_correct_style(self):
        raw = _raw(console_messages=[
            {"type": "log",   "text": "hello"},
            {"type": "warn",  "text": "uh oh"},
            {"type": "error", "text": "boom"},
        ])
        renderer = _make_renderer("browser_console", raw)
        result = renderer.build()
        import io
        from rich.console import Console
        buf = io.StringIO()
        con = Console(file=buf, highlight=False, markup=False, no_color=True, width=200)
        con.print(result)
        text = buf.getvalue()
        assert "hello" in text
        assert "uh oh" in text
        assert "boom" in text

    def test_info_level_uses_cyan(self):
        raw = _raw(console_messages=[{"type": "info", "text": "info message"}])
        renderer = _make_renderer("browser_console", raw)
        result = renderer.build()
        from rich.text import Text
        # build() returns a Group; check the first element's spans
        segments = list(result.renderables)
        line: Text = segments[0]
        assert any("cyan" in str(s.style) for s in line._spans), "info level should use cyan style"

    def test_js_errors_section_shows_badge(self):
        raw = _raw(
            console_messages=[],
            js_errors=[{"message": "Uncaught TypeError", "stack": ""}],
        )
        renderer = _make_renderer("browser_console", raw)
        result = renderer.build()
        import io
        from rich.console import Console
        buf = io.StringIO()
        con = Console(file=buf, highlight=False, markup=False, no_color=True, width=200)
        con.print(result)
        text = buf.getvalue()
        assert "JS error" in text
        assert "Uncaught TypeError" in text

    def test_js_error_stack_truncated_to_four_frames(self):
        stack_lines = "\n".join(f"  at fn{i}:1" for i in range(10))
        raw = _raw(
            js_errors=[{"message": "err", "stack": stack_lines}],
        )
        renderer = _make_renderer("browser_console", raw)
        result = renderer.build()
        import io
        from rich.console import Console
        buf = io.StringIO()
        con = Console(file=buf, highlight=False, markup=False, no_color=True, width=400)
        con.print(result)
        text = buf.getvalue()
        shown = sum(1 for i in range(10) if f"fn{i}:1" in text)
        assert shown == 4, f"Expected 4 frames, got {shown}"

    def test_no_output_shows_placeholder(self):
        raw = _raw(console_messages=[], js_errors=[])
        renderer = _make_renderer("browser_console", raw)
        result = renderer.build()
        from rich.text import Text
        assert isinstance(result, Text)
        assert "no console output" in str(result)

    def test_malformed_json_passthrough(self):
        renderer = _make_renderer("browser_console", "not json at all")
        result = renderer.build()
        from rich.text import Text
        assert isinstance(result, Text)
        assert "not json" in str(result)

    def test_can_render_only_for_console(self):
        console_p = _payload("browser_console", "{}")
        assert BrowserConsoleRenderer.can_render(None, console_p) is True
        for name in ("browser_navigate", "browser_click", "read_file"):
            p = _payload(name, "{}")
            assert BrowserConsoleRenderer.can_render(None, p) is False, f"{name} should be False"

    def test_summary_errors_present(self):
        raw = _raw(console_messages=[
            {"type": "log",   "text": "ok"},
            {"type": "error", "text": "bad"},
        ])
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "✗" in s
        assert "1 error(s)" in s
        assert "0 warn(s)" in s
        assert "2 total" in s

    def test_summary_warns_only(self):
        raw = _raw(console_messages=[
            {"type": "log",  "text": "a"},
            {"type": "log",  "text": "b"},
            {"type": "warn", "text": "c"},
        ])
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "⚠" in s
        assert "1 warn(s)" in s
        assert "3 messages" in s

    def test_summary_clean(self):
        raw = _raw(console_messages=[
            {"type": "log", "text": str(i)} for i in range(5)
        ])
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "✓" in s
        assert "5 message(s)" in s


class TestSummaryEdgeCases:
    """BR-CON-3"""

    def test_summary_prefers_total_errors_field(self):
        raw = _raw(
            console_messages=[{"type": "error", "text": "x"}],
            js_errors=[],
            total_errors=3,
        )
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "3 error(s)" in s

    def test_summary_falls_back_to_count_when_total_errors_zero(self):
        raw = _raw(
            console_messages=[
                {"type": "error", "text": "e1"},
                {"type": "error", "text": "e2"},
            ],
            total_errors=0,
        )
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "2 error(s)" in s

    def test_summary_falls_back_to_count_when_total_errors_absent(self):
        raw = _raw(
            console_messages=[
                {"type": "error", "text": "only one"},
            ],
        )
        renderer = _make_renderer("browser_console", raw)
        s = renderer.summary_line()
        assert "1 error(s)" in s
