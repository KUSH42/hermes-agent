"""tests/tui/test_render_code_json.py

Pure-unit tests for CodeRenderer (R-C1..R-C4) and JsonRenderer (R-J1..R-J3).
No run_test required.
"""
from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw="", args=None):
    from hermes_cli.tui.tool_payload import ToolPayload
    from hermes_cli.tui.tool_category import ToolCategory
    return ToolPayload(
        tool_name="test",
        category=ToolCategory.CODE,
        args=args or {},
        input_display=None,
        output_raw=output_raw,
    )


def _make_cls_result(kind=None):
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    from dataclasses import field
    return ClassificationResult(
        kind=kind or ResultKind.CODE,
        confidence=1.0,
    )


def _make_code_renderer(output_raw="", args=None, app=None):
    from hermes_cli.tui.body_renderers.code import CodeRenderer
    from hermes_cli.tui.tool_payload import ResultKind
    payload = _make_payload(output_raw=output_raw, args=args)
    cls_result = _make_cls_result(kind=ResultKind.CODE)
    r = CodeRenderer(payload, cls_result, app=app)
    return r


def _make_json_renderer(output_raw="", app=None):
    from hermes_cli.tui.body_renderers.json import JsonRenderer
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ToolPayload
    payload = ToolPayload(
        tool_name="test",
        category=ToolCategory.CODE,
        args={},
        input_display=None,
        output_raw=output_raw,
    )
    cls_result = ClassificationResult(kind=ResultKind.JSON, confidence=1.0)
    return JsonRenderer(payload, cls_result, app=app)


def _make_app_with_theme(theme="dracula"):
    app = MagicMock()
    app.get_css_variables.return_value = {"syntax-theme": theme}
    # Prevent MagicMock from making config look like a real dict with threshold=1
    app.config = {}
    return app


# ---------------------------------------------------------------------------
# R-C1 — TestCodeRendererTheme
# ---------------------------------------------------------------------------

class TestCodeRendererTheme:
    def _syntax_theme_name(self, syntax) -> str:
        """Extract the theme name string from a rich.syntax.Syntax object."""
        # Rich stores the pygments style class, not the string name; derive it.
        try:
            return syntax._theme._pygments_style_class.__name__.lower()
        except Exception:
            return ""

    def test_code_renderer_uses_skin_theme(self):
        from rich.syntax import Syntax
        from rich.console import Group
        app = _make_app_with_theme("dracula")
        r = _make_code_renderer(output_raw="x = 1\n" * 6, app=app)
        result = r.build()
        # Group wraps (header, syntax)
        assert isinstance(result, Group)
        renderables = list(result.renderables)
        syntax = renderables[1]
        assert isinstance(syntax, Syntax)
        assert "dracula" in self._syntax_theme_name(syntax)

    def test_code_renderer_background_transparent(self):
        from rich.syntax import Syntax
        from rich.console import Group
        app = _make_app_with_theme("monokai")
        r = _make_code_renderer(output_raw="x = 1\n" * 6, app=app)
        result = r.build()
        renderables = list(result.renderables)
        syntax = renderables[1]
        assert isinstance(syntax, Syntax)
        assert syntax.background_color == "default"

    def test_no_monokai_literals(self):
        import glob
        import os
        body_renderers_dir = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "hermes_cli", "tui", "body_renderers",
        )
        py_files = glob.glob(os.path.join(body_renderers_dir, "*.py"))
        assert py_files, "No body_renderers/*.py files found"
        hits = []
        for path in py_files:
            with open(path) as f:
                for lineno, line in enumerate(f, 1):
                    if '"monokai"' in line or "'monokai'" in line:
                        hits.append(f"{os.path.basename(path)}:{lineno}: {line.rstrip()}")
        assert hits == [], "Hardcoded 'monokai' literals found:\n" + "\n".join(hits)


# ---------------------------------------------------------------------------
# R-C2 — TestCodeLineNumbers
# ---------------------------------------------------------------------------

class TestCodeLineNumbers:
    def test_short_snippet_no_line_numbers(self):
        from rich.syntax import Syntax
        from rich.console import Group
        code = "a = 1\nb = 2\nc = 3"  # 3 lines
        r = _make_code_renderer(output_raw=code)
        result = r.build()
        syntax = list(result.renderables)[1]
        assert not syntax.line_numbers

    def test_long_snippet_line_numbers(self):
        from rich.syntax import Syntax
        from rich.console import Group
        code = "\n".join(f"x = {i}" for i in range(6))  # 6 lines
        r = _make_code_renderer(output_raw=code)
        result = r.build()
        syntax = list(result.renderables)[1]
        assert syntax.line_numbers

    def test_start_line_forces_on(self):
        from rich.syntax import Syntax
        from rich.console import Group
        code = "a = 1\nb = 2\nc = 3"  # only 3 lines
        r = _make_code_renderer(output_raw=code, args={"start_line": 100})
        result = r.build()
        syntax = list(result.renderables)[1]
        assert syntax.line_numbers
        assert syntax.start_line == 100


# ---------------------------------------------------------------------------
# R-C3 — TestCodeFenceDetection
# ---------------------------------------------------------------------------

class TestCodeFenceDetection:
    def _detect(self, text):
        from hermes_cli.tui.body_renderers.code import _detect_lang_from_fence
        return _detect_lang_from_fence(text)

    def test_fence_preserves_trailing_newline(self):
        text = "```py\nx\n\n```"
        lang, body = self._detect(text)
        assert lang == "py"
        # blank line between x and closing ``` means body = "x\n"
        assert body == "x\n"

    def test_fence_preserves_trailing_whitespace_before_fence(self):
        text = "```py\nx   \n```"
        lang, body = self._detect(text)
        assert lang == "py"
        assert body == "x   "

    def test_fence_mid_string_not_matched(self):
        text = "```py\nx\n```\nmore\n```"
        lang, body = self._detect(text)
        assert lang == ""
        assert body == text

    def test_fence_unclosed_returns_unmodified(self):
        text = "```py\nx\n"
        lang, body = self._detect(text)
        assert lang == ""
        assert body == text


# ---------------------------------------------------------------------------
# R-C4 — TestCodeHeader
# ---------------------------------------------------------------------------

class TestCodeHeader:
    def _plain(self, renderable):
        from rich.console import Console
        con = Console(force_terminal=False, no_color=True, width=200)
        with con.capture() as cap:
            con.print(renderable)
        return cap.get()

    def test_header_shows_path_lang_linecount(self):
        lines = "\n".join(f"    x = {i}" for i in range(247))
        r = _make_code_renderer(output_raw=lines, args={"path": "foo.py"})
        result = r.build()
        text = self._plain(result)
        assert "foo.py" in text
        assert "python" in text
        assert "247 lines" in text

    def test_header_no_path_shows_lang(self):
        code = "```python\nprint('hi')\n```"
        r = _make_code_renderer(output_raw=code)
        result = r.build()
        text = self._plain(result)
        assert "(python)" in text

    def test_header_detection_failed_shows_text(self):
        r = _make_code_renderer(output_raw="hello world no fence")
        result = r.build()
        text = self._plain(result)
        assert "(text)" in text


# ---------------------------------------------------------------------------
# R-J1 — TestJsonRenderer
# ---------------------------------------------------------------------------

class TestJsonRenderer:
    def _build_syntax(self, raw, app=None):
        from rich.syntax import Syntax
        r = _make_json_renderer(output_raw=raw, app=app)
        result = r.build()
        assert isinstance(result, Syntax), f"Expected Syntax, got {type(result)}"
        return result

    def test_json_output_is_valid_json(self):
        raw = json.dumps({"a": 1, "b": True})
        syntax = self._build_syntax(raw)
        parsed = json.loads(syntax.code)
        assert parsed == {"a": 1, "b": True}

    def test_json_output_uses_skin_theme(self):
        app = _make_app_with_theme("dracula")
        raw = json.dumps({"x": 42})
        syntax = self._build_syntax(raw, app=app)
        # Rich stores theme via _theme._pygments_style_class, not as a string in repr
        try:
            theme_name = syntax._theme._pygments_style_class.__name__.lower()
        except Exception:
            theme_name = ""
        assert "dracula" in theme_name

    def test_json_double_quoted_keys(self):
        raw = json.dumps({"a": 1})
        syntax = self._build_syntax(raw)
        assert '"a": 1' in syntax.code
        assert "'a': 1" not in syntax.code


# ---------------------------------------------------------------------------
# R-J2 — TestJsonParseFailure
# ---------------------------------------------------------------------------

class TestJsonParseFailure:
    def _build_failure(self, raw):
        from rich.console import Group
        r = _make_json_renderer(output_raw=raw)
        result = r.build()
        assert isinstance(result, Group), f"Expected Group on failure, got {type(result)}"
        items = list(result.renderables)
        return items

    def test_parse_failure_prepends_hint(self):
        from rich.text import Text
        items = self._build_failure("{not json")
        hint = items[0]
        assert isinstance(hint, Text)
        assert hint.plain.startswith("JSON parse failed at line")

    def test_parse_failure_hint_is_dim(self):
        """Parse failure hint should use a muted/dim style (dim or a muted hex color)."""
        from rich.text import Text
        items = self._build_failure("{not json")
        hint = items[0]
        # Accept both "dim" style and muted hex colors (SkinColors.muted returns a hex string)
        style_str = str(hint.style)
        assert "dim" in str(hint._spans) or "dim" in style_str or style_str.startswith("#"), (
            f"Expected dim or muted style, got: {style_str!r}"
        )

    def test_parse_failure_body_preserves_raw(self):
        from rich.text import Text
        raw = "{not json"
        items = self._build_failure(raw)
        body = items[1]
        assert isinstance(body, Text)
        assert raw in body.plain


# ---------------------------------------------------------------------------
# R-J3 — TestJsonCollapse
# ---------------------------------------------------------------------------

class TestJsonCollapse:
    def _large_json(self, n=300):
        data = {f"key_{i}": f"value_{i}" for i in range(n)}
        return json.dumps(data), data

    def _small_json(self, n=10):
        data = {f"key_{i}": i for i in range(n)}
        return json.dumps(data), data

    def test_small_json_inline(self):
        from rich.syntax import Syntax
        raw, _ = self._small_json(10)
        r = _make_json_renderer(output_raw=raw)
        result = r.build()
        assert isinstance(result, Syntax), f"Expected Syntax for small JSON, got {type(result)}"

    def test_large_json_summary(self):
        from rich.text import Text
        raw, _ = self._large_json(300)
        r = _make_json_renderer(output_raw=raw)
        result = r.build()
        assert not isinstance(result, __import__("rich.syntax", fromlist=["Syntax"]).Syntax)
        # Should be a RichText with "collapsed" in it
        plain = result.plain if hasattr(result, "plain") else str(result)
        assert "collapsed" in plain

    def _extract_collapse_widget(self, widget):
        """Extract _JsonCollapseWidget from either a direct widget or a BodyFrame body."""
        from hermes_cli.tui.body_renderers.json import _JsonCollapseWidget
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        if isinstance(widget, _JsonCollapseWidget):
            return widget
        if isinstance(widget, BodyFrame):
            body = widget._body
            if isinstance(body, _JsonCollapseWidget):
                return body
        return widget

    def test_large_json_widget_has_expand_button(self):
        from hermes_cli.tui.body_renderers.json import _JsonCollapseWidget
        raw, _ = self._large_json(300)
        r = _make_json_renderer(output_raw=raw)
        result = r.build_widget()
        widget = self._extract_collapse_widget(result)
        assert isinstance(widget, _JsonCollapseWidget), f"Expected _JsonCollapseWidget, got {type(widget)}"
        summary_plain = widget._summary.content.plain
        assert "[expand]" in summary_plain
        assert widget._syntax_view.display is False

    def test_large_json_toggle_shows_syntax(self):
        from hermes_cli.tui.body_renderers.json import _JsonCollapseWidget
        raw, _ = self._large_json(300)
        r = _make_json_renderer(output_raw=raw)
        result = r.build_widget()
        widget = self._extract_collapse_widget(result)
        assert isinstance(widget, _JsonCollapseWidget), f"Expected _JsonCollapseWidget, got {type(widget)}"
        assert widget._syntax_view.display is False
        widget._toggle_expand()
        assert widget._syntax_view.display is True
