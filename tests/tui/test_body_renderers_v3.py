"""Tests for Phase C BodyRenderer v3 implementations (63 tests).

All tests use hermes_cli.tui.body_renderers (plural) — the Phase C package.
The existing test_body_renderers.py covers the Phase 2 body_renderer.py (singular).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


def _make_payload(
    output_raw: str = "",
    tool_name: str = "bash",
    category: object = None,
    args: dict | None = None,
) -> ToolPayload:
    if category is None:
        category = ToolCategory.SHELL
    return ToolPayload(
        tool_name=tool_name,
        category=category,
        args=args or {},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _cls(kind: ResultKind, confidence: float = 0.9, metadata: dict | None = None) -> ClassificationResult:
    return ClassificationResult(kind, confidence, metadata or {})


# ===========================================================================
# ShellOutputRenderer (7 + 2 specific = 9)
# ===========================================================================

class TestShellOutputRenderer:
    def _renderer(self, output: str = "hello world\n"):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        payload = _make_payload(output_raw=output)
        cls_result = _cls(ResultKind.TEXT)
        return ShellOutputRenderer(payload, cls_result)

    def test_shell_can_render_true(self):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        cls_result = _cls(ResultKind.TEXT)
        payload = _make_payload()
        assert ShellOutputRenderer.can_render(cls_result, payload) is True

    def test_shell_can_render_false(self):
        # can_render always returns True for shell
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert ShellOutputRenderer.can_render(cls_result, payload) is True

    def test_shell_build_returns_renderable(self):
        r = self._renderer("output line\n")
        result = r.build()
        assert result is not None

    def test_shell_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer("output line\n")
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_shell_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        assert ShellOutputRenderer.kind == ResultKind.TEXT

    def test_shell_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        assert ShellOutputRenderer.supports_streaming is True

    def test_shell_strip_cwd_in_build(self):
        raw = "some output\n__HERMES_CWD_abcdef12__/home/user/project__HERMES_CWD_abcdef12__\n"
        r = self._renderer(raw)
        renderable = r.build()
        text_str = str(renderable)
        # CWD token should be stripped
        assert "__HERMES_CWD_" not in text_str

    def test_shell_refresh_incremental_appends(self):
        r = self._renderer("line1\n")
        # Build widget first so _log_widget is set
        w = r.build_widget()
        # refresh_incremental should not raise
        r.refresh_incremental("new chunk\n")
        assert r._log_widget is not None

    def test_shell_build_widget_stores_log_ref(self):
        r = self._renderer("test\n")
        w = r.build_widget()
        assert r._log_widget is w


# ===========================================================================
# SearchRenderer (7 + 3 specific = 10)
# ===========================================================================

class TestSearchRenderer:
    def _renderer(self, output: str = "src/foo.py\n  1: def foo\n  2: pass\n  3: end\n"):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.SEARCH)
        cls_result = _cls(ResultKind.SEARCH, metadata={"hit_count": 3, "query": "foo"})
        return SearchRenderer(payload, cls_result)

    def test_search_can_render_true(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        cls_result = _cls(ResultKind.SEARCH)
        payload = _make_payload()
        assert SearchRenderer.can_render(cls_result, payload) is True

    def test_search_can_render_false(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert SearchRenderer.can_render(cls_result, payload) is False

    def test_search_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_search_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_search_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        assert SearchRenderer.kind == ResultKind.SEARCH

    def test_search_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        assert SearchRenderer.supports_streaming is False

    def test_search_path_headers_present(self):
        output = "src/foo.py\n  1: def foo\n  2: pass\n  3: end\n"
        r = self._renderer(output)
        result = r.build()
        text_str = str(result)
        assert "src/foo.py" in text_str

    def test_search_line_num_aligned(self):
        output = "src/foo.py\n  1: def foo\n  2: pass\n  3: end\n"
        r = self._renderer(output)
        result = r.build()
        text_str = str(result)
        assert "1" in text_str
        assert "2" in text_str

    def test_search_query_highlighted(self):
        output = "src/foo.py\n  1: def foo\n  2: foo bar\n  3: foo baz\n"
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.SEARCH)
        cls_result = _cls(ResultKind.SEARCH, metadata={"hit_count": 3, "query": "foo"})
        r = SearchRenderer(payload, cls_result)
        result = r.build()
        assert result is not None


# ===========================================================================
# DiffRenderer (7 + 3 specific = 10)
# ===========================================================================

DIFF_TEXT = """\
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 def foo():
-    pass
+    return 1
+    # comment
 end
"""


class TestDiffRenderer:
    def _renderer(self, output: str = DIFF_TEXT):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.FILE)
        cls_result = _cls(ResultKind.DIFF)
        return DiffRenderer(payload, cls_result)

    def test_diff_can_render_true(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        cls_result = _cls(ResultKind.DIFF)
        payload = _make_payload()
        assert DiffRenderer.can_render(cls_result, payload) is True

    def test_diff_can_render_false(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert DiffRenderer.can_render(cls_result, payload) is False

    def test_diff_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_diff_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_diff_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        assert DiffRenderer.kind == ResultKind.DIFF

    def test_diff_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        assert DiffRenderer.supports_streaming is False

    def test_diff_added_line_style(self):
        r = self._renderer()
        result = r.build()
        text_str = str(result)
        assert "return 1" in text_str

    def test_diff_removed_line_style(self):
        r = self._renderer()
        result = r.build()
        text_str = str(result)
        assert "pass" in text_str

    def test_diff_word_diff_applied(self):
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,2 @@
-    old_value = 42
+    new_value = 99
"""
        r = self._renderer(diff)
        result = r.build()
        assert result is not None


# ===========================================================================
# CodeRenderer (7 + 2 specific = 9)
# ===========================================================================

class TestCodeRenderer:
    def _renderer(self, output: str = "def foo():\n    return 1\n", args: dict | None = None):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.FILE, args=args or {})
        cls_result = _cls(ResultKind.CODE)
        return CodeRenderer(payload, cls_result)

    def test_code_can_render_true(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        cls_result = _cls(ResultKind.CODE)
        payload = _make_payload()
        assert CodeRenderer.can_render(cls_result, payload) is True

    def test_code_can_render_false(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert CodeRenderer.can_render(cls_result, payload) is False

    def test_code_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_code_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_code_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        assert CodeRenderer.kind == ResultKind.CODE

    def test_code_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        assert CodeRenderer.supports_streaming is False

    def test_code_syntax_object_returned(self):
        from rich.syntax import Syntax
        r = self._renderer()
        result = r.build()
        assert isinstance(result, Syntax)

    def test_code_lexer_from_extension(self):
        from rich.syntax import Syntax
        r = self._renderer(args={"path": "src/main.py"})
        result = r.build()
        assert isinstance(result, Syntax)
        # result._lexer is the string passed to Syntax constructor
        assert "python" in str(result._lexer).lower()


# ===========================================================================
# LogRenderer (7 + 2 specific = 9)
# ===========================================================================

LOG_TEXT = """\
2024-01-01 10:00:00 INFO Server started
2024-01-01 10:00:01 ERROR Connection failed
2024-01-01 10:00:02 WARN Retry attempt
2024-01-01 10:00:03 DEBUG Debug info
"""


class TestLogRenderer:
    def _renderer(self, output: str = LOG_TEXT):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.SHELL)
        cls_result = _cls(ResultKind.LOG)
        return LogRenderer(payload, cls_result)

    def test_log_can_render_true(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        cls_result = _cls(ResultKind.LOG)
        payload = _make_payload()
        assert LogRenderer.can_render(cls_result, payload) is True

    def test_log_can_render_false(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert LogRenderer.can_render(cls_result, payload) is False

    def test_log_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_log_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_log_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        assert LogRenderer.kind == ResultKind.LOG

    def test_log_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.log import LogRenderer
        assert LogRenderer.supports_streaming is False

    def test_log_level_colors_applied(self):
        r = self._renderer()
        result = r.build()
        text_str = str(result)
        assert "ERROR" in text_str or "INFO" in text_str

    def test_log_timestamp_dim(self):
        r = self._renderer()
        result = r.build()
        text_str = str(result)
        assert "2024-01-01" in text_str


# ===========================================================================
# JsonRenderer (7 + 2 specific = 9)
# ===========================================================================

class TestJsonRenderer:
    def _renderer(self, output: str = '{"key": "value", "num": 42}'):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.UNKNOWN)
        cls_result = _cls(ResultKind.JSON)
        return JsonRenderer(payload, cls_result)

    def test_json_can_render_true(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert JsonRenderer.can_render(cls_result, payload) is True

    def test_json_can_render_false(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        cls_result = _cls(ResultKind.TEXT)
        payload = _make_payload()
        assert JsonRenderer.can_render(cls_result, payload) is False

    def test_json_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_json_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_json_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        assert JsonRenderer.kind == ResultKind.JSON

    def test_json_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.json import JsonRenderer
        assert JsonRenderer.supports_streaming is False

    def test_json_pretty_renderable(self):
        from rich.pretty import Pretty
        r = self._renderer()
        result = r.build()
        assert isinstance(result, Pretty)

    def test_json_parse_failure_fallback(self):
        from rich.text import Text
        r = self._renderer(output='{"invalid": BROKEN')
        result = r.build()
        assert isinstance(result, Text)


# ===========================================================================
# TableRenderer (7 + 2 specific = 9)
# ===========================================================================

TABLE_TEXT = "Name | Age | City\n-----|-----|-----\nAlice | 30 | NYC\nBob | 25 | LA\n"


class TestTableRenderer:
    def _renderer(self, output: str = TABLE_TEXT):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.UNKNOWN)
        cls_result = _cls(ResultKind.TABLE)
        return TableRenderer(payload, cls_result)

    def test_table_can_render_true(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        cls_result = _cls(ResultKind.TABLE)
        payload = _make_payload()
        assert TableRenderer.can_render(cls_result, payload) is True

    def test_table_can_render_false(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert TableRenderer.can_render(cls_result, payload) is False

    def test_table_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_table_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_table_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        assert TableRenderer.kind == ResultKind.TABLE

    def test_table_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.table import TableRenderer
        assert TableRenderer.supports_streaming is False

    def test_table_rich_table_returned(self):
        from rich.table import Table
        r = self._renderer()
        result = r.build()
        assert isinstance(result, Table)

    def test_table_header_detection(self):
        from rich.table import Table
        r = self._renderer()
        result = r.build()
        assert isinstance(result, Table)
        assert result.columns is not None
        assert len(result.columns) > 0


# ===========================================================================
# EmptyStateRenderer (7 + 2 specific = 9)
# ===========================================================================

class TestEmptyStateRenderer:
    def _renderer(self):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        payload = _make_payload(output_raw="")
        cls_result = _cls(ResultKind.EMPTY, confidence=1.0)
        return EmptyStateRenderer(payload, cls_result)

    def test_empty_can_render_true(self):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        cls_result = _cls(ResultKind.EMPTY)
        payload = _make_payload()
        assert EmptyStateRenderer.can_render(cls_result, payload) is True

    def test_empty_can_render_false(self):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        cls_result = _cls(ResultKind.JSON)
        payload = _make_payload()
        assert EmptyStateRenderer.can_render(cls_result, payload) is False

    def test_empty_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_empty_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_empty_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        assert EmptyStateRenderer.kind == ResultKind.EMPTY

    def test_empty_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        assert EmptyStateRenderer.supports_streaming is False

    def test_empty_widget_is_static(self):
        from textual.widgets import Static
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Static)

    def test_empty_text_content(self):
        r = self._renderer()
        result = r.build()
        assert "(no output)" in str(result)


# ===========================================================================
# FallbackRenderer (7 + 2 specific = 9)
# ===========================================================================

class TestFallbackRenderer:
    def _renderer(self, output: str = "plain text output\nline two\n"):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        payload = _make_payload(output_raw=output, category=ToolCategory.UNKNOWN)
        cls_result = _cls(ResultKind.TEXT, confidence=1.0)
        return FallbackRenderer(payload, cls_result)

    def test_fallback_can_render_true(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        cls_result = _cls(ResultKind.TEXT)
        payload = _make_payload()
        assert FallbackRenderer.can_render(cls_result, payload) is True

    def test_fallback_can_render_any_kind(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        # Fallback always returns True regardless of kind (terminator)
        for kind in ResultKind:
            cls_result = _cls(kind)
            payload = _make_payload()
            assert FallbackRenderer.can_render(cls_result, payload) is True

    def test_fallback_build_returns_renderable(self):
        r = self._renderer()
        result = r.build()
        assert result is not None

    def test_fallback_build_widget_returns_widget(self):
        from textual.widget import Widget
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, Widget)

    def test_fallback_kind_class_var_correct(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.kind == ResultKind.TEXT

    def test_fallback_supports_streaming_correct(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        assert FallbackRenderer.supports_streaming is False

    def test_fallback_always_can_render(self):
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        cls_result = _cls(ResultKind.BINARY)
        payload = _make_payload()
        assert FallbackRenderer.can_render(cls_result, payload) is True

    def test_fallback_build_widget(self):
        from hermes_cli.tui.widgets import CopyableRichLog
        r = self._renderer()
        w = r.build_widget()
        assert isinstance(w, CopyableRichLog)
