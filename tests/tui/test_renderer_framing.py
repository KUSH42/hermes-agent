"""Tests for RF-1..RF-6 renderer framing spec (spec_tool_renderer_framing.md)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.body_renderers._frame import BodyFrame
from hermes_cli.tui.body_renderers._grammar import BodyFooter, SkinColors, build_parse_failure
from hermes_cli.tui.body_renderers.code import CodeRenderer
from hermes_cli.tui.body_renderers.diff import DiffRenderer
from hermes_cli.tui.body_renderers.json import JsonRenderer
from hermes_cli.tui.body_renderers.log import LogRenderer
from hermes_cli.tui.body_renderers.search import SearchRenderer
from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
from hermes_cli.tui.body_renderers.table import TableRenderer
from hermes_cli.tui.tool_panel.density import DensityTier
from textual.widgets import Static
from textual.widget import Widget
from rich.text import Text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw="", args=None, **kwargs):
    payload = MagicMock()
    payload.output_raw = output_raw
    payload.args = args or {}
    payload.header_has_cwd = kwargs.get("header_has_cwd", False)
    payload.exit_code = kwargs.get("exit_code", None)
    payload.stderr_raw = kwargs.get("stderr_raw", None)
    payload.category = kwargs.get("category", MagicMock())
    return payload


def _make_cls_result(kind=None, confidence=1.0, metadata=None):
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    return ClassificationResult(
        kind=kind or ResultKind.TEXT,
        confidence=confidence,
        metadata=metadata or {},
    )


def _plain(renderable) -> str:
    """Extract plain text from a Rich renderable (Text object)."""
    if isinstance(renderable, Text):
        return renderable.plain
    return str(renderable)


# ---------------------------------------------------------------------------
# TestRF1BodyFrame — 5 tests
# ---------------------------------------------------------------------------

class TestRF1BodyFrame:
    def test_frame_renders_all_three_slots(self):
        """compose yields header Static, body Static, footer BodyFooter; 3 children."""
        header = Text("hdr")
        body = Text("body")
        footer = BodyFooter(("y", "copy"))
        frame = BodyFrame(header=header, body=body, footer=footer)
        children = list(frame.compose())
        assert len(children) == 3
        assert isinstance(children[0], Static)
        assert isinstance(children[1], Static)
        assert isinstance(children[2], BodyFooter)

    def test_frame_omits_header_when_none(self):
        """header=None: compose yields body + footer only; no .body-frame--header."""
        body = Text("body")
        footer = BodyFooter(("y", "copy"))
        frame = BodyFrame(header=None, body=body, footer=footer)
        children = list(frame.compose())
        assert len(children) == 2
        assert not any(
            isinstance(c, Static) and "body-frame--header" in c.classes
            for c in children
        )

    def test_frame_omits_footer_when_none(self):
        """footer=None: compose yields header + body only; no BodyFooter child."""
        header = Text("hdr")
        body = Text("body")
        frame = BodyFrame(header=header, body=body, footer=None)
        children = list(frame.compose())
        assert len(children) == 2
        assert not any(isinstance(c, BodyFooter) for c in children)

    def test_frame_body_widget_mounted_directly(self):
        """body is a pre-built Widget: compose yields it (not wrapped in Static)."""
        from textual.widgets import Label
        body_widget = Label("test")
        frame = BodyFrame(header=None, body=body_widget, footer=None)
        children = list(frame.compose())
        assert len(children) == 1
        assert children[0] is body_widget
        assert "body-frame--body" in children[0].classes

    def test_frame_classes_propagated(self):
        """classes='my-class' kwarg passed through to BodyFrame root."""
        frame = BodyFrame(header=None, body=Text("b"), footer=None, classes="my-class")
        assert "my-class" in frame.classes


# ---------------------------------------------------------------------------
# TestRF2CodeDiffSearch — 6 tests
# ---------------------------------------------------------------------------

class TestRF2CodeDiffSearch:
    def _code_renderer(self, raw="x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6", path="foo.py"):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        payload = _make_payload(output_raw=raw, args={"path": path})
        cls_result = ClassificationResult(kind=ResultKind.CODE, confidence=1.0)
        return CodeRenderer(payload, cls_result)

    def test_code_renderer_returns_body_frame(self):
        r = self._code_renderer()
        result = r.build_widget()
        assert isinstance(result, BodyFrame)

    def test_code_frame_has_path_header(self):
        r = self._code_renderer()
        frame = r.build_widget()
        children = list(frame.compose())
        # header is first child and has class body-frame--header
        header_children = [c for c in children if isinstance(c, Static) and "body-frame--header" in c.classes]
        assert len(header_children) == 1

    def test_code_frame_has_copy_footer(self):
        r = self._code_renderer()
        frame = r.build_widget()
        assert isinstance(frame._footer, BodyFooter)
        rendered = frame._footer.render()
        assert "[y]" in _plain(rendered)

    def _diff_renderer(self):
        raw = (
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old line\n"
            "+new line\n"
        )
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.DIFF, confidence=1.0)
        return DiffRenderer(payload, cls_result)

    def test_diff_renderer_returns_body_frame(self):
        r = self._diff_renderer()
        result = r.build_widget()
        assert isinstance(result, BodyFrame)

    def test_diff_frame_has_summary_header(self):
        import re
        r = self._diff_renderer()
        frame = r.build_widget()
        assert frame._header is not None
        assert re.search(r"\d+ file\(s\) changed", _plain(frame._header))

    def test_search_renderer_returns_body_frame(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        raw = "file.py\n1: match line\n2- context line\n"
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.SEARCH, confidence=1.0, metadata={"hit_count": 1})
        r = SearchRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        assert frame._header is None


# ---------------------------------------------------------------------------
# TestRF3ShellJsonTableLog — 8 tests
# ---------------------------------------------------------------------------

class TestRF3ShellJsonTableLog:
    def test_shell_renderer_frame_with_cwd(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        from unittest.mock import patch
        payload = _make_payload(output_raw="output line", header_has_cwd=False)
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)

        with patch("hermes_cli.tui.cwd_strip.strip_cwd", return_value=("output line", "/home/user")):
            r = ShellOutputRenderer(payload, cls_result)
            frame = r.build_widget()

        assert isinstance(frame, BodyFrame)
        assert frame._header is not None
        assert "/home/user" in _plain(frame._header)

    def test_shell_renderer_frame_no_cwd(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        from unittest.mock import patch
        payload = _make_payload(output_raw="output line", header_has_cwd=False)
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)

        with patch("hermes_cli.tui.cwd_strip.strip_cwd", return_value=("output line", None)):
            r = ShellOutputRenderer(payload, cls_result)
            frame = r.build_widget()

        assert isinstance(frame, BodyFrame)
        assert frame._header is None

    def test_json_renderer_frame_normal(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        raw = json.dumps({"key": "value"})
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.JSON, confidence=1.0)
        r = JsonRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        assert "json" in _plain(frame._header)

    def test_json_renderer_frame_parse_fail(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        raw = "{not valid json!!!"
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.JSON, confidence=1.0)
        r = JsonRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        # Body slot should contain "Parse error" text
        body_children = [c for c in frame.compose() if isinstance(c, Static) and "body-frame--body" in c.classes]
        assert len(body_children) == 1
        rendered_plain = _plain(body_children[0].content)
        assert "Parse error" in rendered_plain

    def test_table_renderer_frame_with_rows_cols(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        # 3 data rows, 4 cols (pipe-delimited, first row is header)
        raw = "a | b | c | d\n" + "-|-|-|-\n" + "1 | 2 | 3 | 4\n" + "5 | 6 | 7 | 8\n" + "9 | 10 | 11 | 12\n"
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.TABLE, confidence=1.0)
        r = TableRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        header_plain = _plain(frame._header)
        assert "3 rows" in header_plain
        assert "4 cols" in header_plain

    def test_log_renderer_frame_with_level_counts(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        raw = "2024-01-01 00:00:00 INFO msg1\n2024-01-01 00:00:01 INFO msg2\n2024-01-01 00:00:02 WARN wmsg\n"
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.LOG, confidence=1.0)
        r = LogRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        footer_text = _plain(frame._footer.render())
        assert "INFO 2" in footer_text
        assert "WARN 1" in footer_text
        assert "ERROR 0" in footer_text

    def test_log_renderer_level_counts_match_body(self):
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        raw = "INFO line1\nERROR line2\nINFO line3\n"
        payload = _make_payload(output_raw=raw)
        cls_result = ClassificationResult(kind=ResultKind.LOG, confidence=1.0)
        r = LogRenderer(payload, cls_result)
        _, counts = r._build_body_with_counts(raw)
        n_info, n_warn, n_err = counts
        assert n_info == 2
        assert n_warn == 0
        assert n_err == 1

    def test_renderers_all_use_body_frame(self):
        """Meta: every Phase C renderer in REGISTRY (exc. Fallback/Empty) returns BodyFrame."""
        from hermes_cli.tui.body_renderers import REGISTRY
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.body_renderers.streaming import (
            ShellRenderer, StreamingCodeRenderer, FileRenderer,
            StreamingSearchRenderer, WebRenderer, AgentRenderer,
            TextRenderer, MCPBodyRenderer,
        )
        _EXCLUDED = {FallbackRenderer, EmptyStateRenderer,
                     ShellRenderer, StreamingCodeRenderer, FileRenderer,
                     StreamingSearchRenderer, WebRenderer, AgentRenderer,
                     TextRenderer, MCPBodyRenderer}

        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult

        _KIND_PAYLOADS = {
            "DiffRenderer": (ResultKind.DIFF, "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"),
            "JsonRenderer": (ResultKind.JSON, '{"k":1}'),
            "SearchRenderer": (ResultKind.SEARCH, "file.py\n1: hit\n"),
            "TableRenderer": (ResultKind.TABLE, "a | b\n-|-\n1 | 2\n"),
            "CodeRenderer": (ResultKind.CODE, "x=1\ny=2\nz=3\na=4\nb=5\nc=6"),
            "LogRenderer": (ResultKind.LOG, "INFO hello\n"),
            "ShellOutputRenderer": (ResultKind.TEXT, "echo hi\n"),
        }

        failures = []
        for cls in REGISTRY:
            if cls in _EXCLUDED:
                continue
            name = cls.__name__
            kind, raw = _KIND_PAYLOADS.get(name, (ResultKind.TEXT, "hello"))
            payload = _make_payload(output_raw=raw)
            payload.category = MagicMock()
            cls_result = ClassificationResult(kind=kind, confidence=1.0, metadata={"hit_count": 1})
            try:
                renderer = cls(payload, cls_result)
                result = renderer.build_widget()
                if not isinstance(result, BodyFrame):
                    failures.append(f"{name}: got {type(result).__name__}")
            except Exception as e:
                failures.append(f"{name}: raised {e!r}")

        assert not failures, "Renderers not returning BodyFrame:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# TestRF4LogLevels — 4 tests
# ---------------------------------------------------------------------------

class TestRF4LogLevels:
    def _render_line(self, line: str) -> str:
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult
        payload = _make_payload(output_raw=line)
        cls_result = ClassificationResult(kind=ResultKind.LOG, confidence=1.0)
        r = LogRenderer(payload, cls_result)
        result, _ = r._build_body_with_counts(line)
        return result.plain

    def test_log_line_prefixed_with_level(self):
        plain = self._render_line("INFO: something happened")
        assert plain.startswith("[INFO]")

    def test_existing_level_tag_not_doubled(self):
        plain = self._render_line("[INFO] already tagged")
        assert "[INFO] [INFO]" not in plain
        assert plain.count("[INFO]") == 1

    def test_unknown_level_no_prefix(self):
        plain = self._render_line("just a plain line with no level")
        assert not plain.startswith("[")

    def test_accessibility_mode_still_prefixed(self):
        """Chip is present regardless of accessibility mode."""
        from unittest.mock import patch
        with patch("hermes_cli.tui.constants.accessibility_mode", return_value=True):
            plain = self._render_line("ERROR something broke")
        assert "[ERROR]" in plain


# ---------------------------------------------------------------------------
# TestRF5BodyFooter — 4 tests
# ---------------------------------------------------------------------------

class TestRF5BodyFooter:
    def test_body_footer_single_entry(self):
        footer = BodyFooter(("y", "copy"))
        rendered = footer.render()
        plain = _plain(rendered)
        assert plain == "[y] copy"

    def test_body_footer_multi_entry_separator(self):
        footer = BodyFooter(("y", "copy"), ("c", "csv"))
        rendered = footer.render()
        plain = _plain(rendered)
        assert "[y] copy" in plain
        assert "[c] csv" in plain
        assert "·" in plain

    def test_body_footer_plain_string_entry(self):
        footer = BodyFooter("INFO 2", "WARN 1")
        rendered = footer.render()
        plain = _plain(rendered)
        assert "INFO 2" in plain
        assert "WARN 1" in plain
        assert "·" in plain
        # No brackets around plain string entries
        assert "[INFO 2]" not in plain

    def test_renderer_no_footer_when_entries_empty(self):
        """Renderer with footer_entries=() should produce BodyFrame with _footer=None."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult

        class _NullRenderer(BodyRenderer):
            kind = None
            footer_entries = ()

            @classmethod
            def can_render(cls, cls_result, payload):
                return True

            def build(self):
                return Text("body")

            def build_widget(self, density=None):
                footer = BodyFooter(*self.footer_entries) if self.footer_entries else None
                return BodyFrame(
                    header=None,
                    body=self.build(),
                    footer=footer,
                    density=density,
                )

        payload = _make_payload(output_raw="x")
        cls_result = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)
        r = _NullRenderer(payload, cls_result)
        frame = r.build_widget()
        assert isinstance(frame, BodyFrame)
        assert frame._footer is None


# ---------------------------------------------------------------------------
# TestRF6TierAware — 3 tests
# ---------------------------------------------------------------------------

class TestRF6TierAware:
    def test_compact_tier_hides_footer(self):
        frame = BodyFrame(
            header=Text("hdr"),
            body=Text("body"),
            footer=BodyFooter(("y", "copy")),
            density=DensityTier.COMPACT,
        )
        assert "body-frame--compact" in frame.classes

    def test_hero_tier_class_set(self):
        frame = BodyFrame(
            header=Text("hdr"),
            body=Text("body"),
            footer=BodyFooter(("y", "copy")),
            density=DensityTier.HERO,
        )
        assert "body-frame--hero" in frame.classes

    def test_trace_tier_class_set(self):
        frame = BodyFrame(
            header=Text("hdr"),
            body=Text("body"),
            footer=BodyFooter(("y", "copy")),
            density=DensityTier.TRACE,
        )
        assert "body-frame--trace" in frame.classes
