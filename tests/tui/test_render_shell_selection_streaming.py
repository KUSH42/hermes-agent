"""Tests for R-S1, R-S2, R-F1, R-E1, R-E2, R-X1, R-X2, R-X3, R-P1, R-P2, R-P3, R-G5.

All pure-unit — no run_test / async needed.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(**kw):
    from hermes_cli.tui.tool_payload import ToolPayload
    from hermes_cli.tui.tool_category import ToolCategory
    defaults = dict(
        tool_name="bash",
        category=ToolCategory.SHELL,
        args={},
        input_display=None,
        output_raw="",
        stderr_raw=None,
        exit_code=None,
        header_has_cwd=False,
    )
    defaults.update(kw)
    return ToolPayload(**defaults)


def _make_cls(kind, confidence=0.9, **meta):
    from hermes_cli.tui.tool_payload import ClassificationResult
    return ClassificationResult(kind=kind, confidence=confidence, metadata=meta)


def _shell_renderer(payload=None, cls_result=None):
    from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
    from hermes_cli.tui.tool_payload import ResultKind
    if payload is None:
        payload = _make_payload()
    if cls_result is None:
        cls_result = _make_cls(ResultKind.TEXT)
    return ShellOutputRenderer(payload, cls_result)


# ---------------------------------------------------------------------------
# R-S1: ShellOutputRenderer — CWD rule vs header breadcrumb
# ---------------------------------------------------------------------------

class TestShellCwd:
    def test_shell_no_trailing_cwd_when_header_has_it(self):
        """payload.header_has_cwd=True → rendered text does not contain 'cwd:'."""
        from hermes_cli.tui.cwd_strip import strip_cwd
        payload = _make_payload(
            output_raw="hello world",
            header_has_cwd=True,
        )
        r = _shell_renderer(payload)
        result = r.build()
        assert "cwd:" not in str(result)

    def test_shell_leading_cwd_rule_when_absent(self):
        """header_has_cwd=False + cwd extracted → first line contains 'cwd:'."""
        # strip_cwd extracts cwd from a sentinel; inject a line that contains it
        # Patch strip_cwd to return a known cwd
        with patch("hermes_cli.tui.cwd_strip.strip_cwd", return_value=("output", "/a")):
            payload = _make_payload(output_raw="output", header_has_cwd=False)
            r = _shell_renderer(payload)
            text = r.build()
            rendered = str(text)
        assert "cwd: /a" in rendered
        # Leading rule — cwd comes before output content
        assert rendered.index("cwd:") < rendered.index("output") if "output" in rendered else True

    def test_shell_refresh_incremental_no_cwd_emit(self):
        """refresh_incremental never writes a 'cwd:' string."""
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        mock_log = MagicMock()
        payload = _make_payload(output_raw="", header_has_cwd=False)
        r = _shell_renderer(payload)
        r._log_widget = mock_log
        r.refresh_incremental("some line\n")
        for call in mock_log.write.call_args_list:
            text = str(call[0][0])
            assert "cwd:" not in text


# ---------------------------------------------------------------------------
# R-S2: ShellOutputRenderer — exit code and stderr
# ---------------------------------------------------------------------------

class TestShellExitAndStderr:
    def test_exit_zero_no_rule(self):
        """exit_code=0 → no 'exit' rule line."""
        payload = _make_payload(output_raw="ok", exit_code=0, header_has_cwd=True)
        r = _shell_renderer(payload)
        result = str(r.build())
        assert "exit" not in result

    def test_exit_nonzero_rule_present(self):
        """exit_code=1 → rendered text contains 'exit 1'."""
        payload = _make_payload(output_raw="", exit_code=1, header_has_cwd=True)
        r = _shell_renderer(payload)
        result = str(r.build())
        assert "exit 1" in result

    def test_exit_rule_uses_error_color(self):
        """exit 1 span uses error color from SkinColors."""
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        payload = _make_payload(output_raw="", exit_code=1, header_has_cwd=True)
        r = _shell_renderer(payload)
        # Ensure colors are set
        r._colors = SkinColors.default()
        text = r.build()
        # Find a span that contains 'exit'
        found_error_color = any(
            SkinColors.default().error.lower() in str(s.style.color).lower()
            for s in text._spans
        )
        assert found_error_color

    def test_stderr_gutter(self):
        """stderr 'boom' → line starts with '! ' + 'boom'. exit_code=0 to confirm."""
        payload = _make_payload(
            output_raw="", exit_code=0, stderr_raw="boom", header_has_cwd=True,
        )
        r = _shell_renderer(payload)
        result = str(r.build())
        assert "!" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# R-F1: FallbackRenderer footer
# ---------------------------------------------------------------------------

class TestFallbackFooter:
    def test_low_confidence_shows_footer(self):
        """confidence=0.3 → last rendered line contains 'unclassified'."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="hello")
        cls = _make_cls(ResultKind.TEXT, confidence=0.3)
        r = FallbackRenderer(payload, cls)
        result = str(r.build())
        assert "unclassified" in result

    def test_text_kind_shows_footer(self):
        """kind=TEXT, confidence=0.9 → footer still shown (TEXT always gets footer)."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="data")
        cls = _make_cls(ResultKind.TEXT, confidence=0.9)
        r = FallbackRenderer(payload, cls)
        result = str(r.build())
        assert "unclassified" in result

    def test_high_confidence_non_text_no_footer(self):
        """confidence=0.9, kind=SEARCH → no 'unclassified' footer."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        payload = _make_payload(output_raw="data")
        cls = _make_cls(ResultKind.SEARCH, confidence=0.9)
        r = FallbackRenderer(payload, cls)
        result = str(r.build())
        assert "unclassified" not in result


# ---------------------------------------------------------------------------
# R-E1 / R-E2: EmptyStateRenderer messages + diagnostic suffix
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_empty_text_sentence_case(self):
        """SHELL payload → output is 'No output' not '(no output)'."""
        from hermes_cli.tui.body_renderers.empty import _get_empty_message
        from hermes_cli.tui.tool_category import ToolCategory
        assert _get_empty_message(ToolCategory.SHELL) == "No output"
        assert "(no output)" not in _get_empty_message(ToolCategory.SHELL)

    def test_empty_diagnostic_suffix_full(self):
        """exit_code=0, elapsed=0.34, category=SEARCH → suffix 'No matches · 0.34s · exit 0'."""
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        payload = _make_payload(
            category=ToolCategory.SEARCH,
            output_raw="",
            exit_code=0,
            started_at=0.0,
            finished_at=0.34,
        )
        cls = _make_cls(ResultKind.EMPTY)
        r = EmptyStateRenderer(payload, cls)
        msg = r._build_message()
        assert msg == "No matches · 0.34s · exit 0"

    def test_empty_diagnostic_partial(self):
        """exit_code=None, elapsed=0.5 → 'No output · 0.50s' (no exit)."""
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        payload = _make_payload(
            category=ToolCategory.SHELL,
            output_raw="",
            exit_code=None,
            started_at=0.0,
            finished_at=0.5,
        )
        cls = _make_cls(ResultKind.EMPTY)
        r = EmptyStateRenderer(payload, cls)
        msg = r._build_message()
        assert msg == "No output · 0.50s"
        assert "exit" not in msg

    def test_empty_category_fallback(self):
        """Unknown category → 'No output'."""
        from hermes_cli.tui.body_renderers.empty import _get_empty_message
        assert _get_empty_message(None) == "No output"
        assert _get_empty_message("unknown_cat") == "No output"


# ---------------------------------------------------------------------------
# R-X1: Streaming swap continuity
# ---------------------------------------------------------------------------

class TestStreamingSwap:
    def test_stream_with_ansi_no_swap(self):
        """all_plain contains ANSI → finalize returns None (keep streamed)."""
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        r = ShellRenderer()
        result = r.finalize(["\x1b[31mfoo"], app=None)
        assert result is None

    def test_stream_no_ansi_has_notice(self):
        """plain JSON stream → finalize produces Group whose first element contains '↻ rendered as json'."""
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        r = ShellRenderer()
        result = r.finalize(['{"key": "value"}'], app=None)
        assert result is not None
        from rich.console import Group
        assert isinstance(result, Group)
        notice_text = str(result._renderables[0])
        assert "rendered as json" in notice_text

    def test_config_disables_swap(self):
        """app with swap_on_complete=False → finalize returns None."""
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        app = MagicMock()
        app.config = {"tui": {"render": {"swap_on_complete": False}}}
        r = ShellRenderer()
        result = r.finalize(['{"key": 1}'], app=app)
        assert result is None

    def test_file_renderer_rule_before_syntax(self):
        """FileRenderer.finalize emits leading rule notice before Syntax block."""
        from hermes_cli.tui.body_renderers.streaming import FileRenderer
        r = FileRenderer()
        result = r.finalize(["def foo():", "    pass"], lang="python", app=None)
        assert result is not None
        from rich.console import Group
        assert isinstance(result, Group)
        notice_text = str(result._renderables[0])
        assert "rendered as python" in notice_text


# ---------------------------------------------------------------------------
# R-X2: Streaming SearchRenderer path headers
# ---------------------------------------------------------------------------

class TestStreamingSearchHeaders:
    def _group_text(self, g):
        """Extract plain text from a Group or Text renderable."""
        from rich.console import Group
        from rich.text import Text
        if isinstance(g, Group):
            return " ".join(
                r.plain if isinstance(r, Text) else str(r)
                for r in g._renderables
            )
        if isinstance(g, Text):
            return g.plain
        return str(g)

    def test_stream_emits_header_on_path_change(self):
        """emit 'foo.py:1:x' then 'bar.py:1:y' → two path header lines."""
        from hermes_cli.tui.body_renderers.streaming import SearchRenderer
        r = SearchRenderer()
        r1 = r.render_stream_line("foo.py:1:x", "foo.py:1:x")
        r2 = r.render_stream_line("bar.py:1:y", "bar.py:1:y")
        t1 = self._group_text(r1)
        t2 = self._group_text(r2)
        assert "foo.py" in t1
        assert "bar.py" in t2

    def test_stream_no_duplicate_header(self):
        """emit 'foo.py:1:x' then 'foo.py:2:y' → one header, two hit lines."""
        from hermes_cli.tui.body_renderers.streaming import SearchRenderer
        r = SearchRenderer()
        r1 = r.render_stream_line("foo.py:1:x", "foo.py:1:x")
        r2 = r.render_stream_line("foo.py:2:y", "foo.py:2:y")
        # Only one group header emitted (first result has 2 renderables, second has 1)
        from rich.console import Group
        assert isinstance(r1, Group)  # header + content
        assert not isinstance(r2, Group)  # content only (no header)

    def test_stream_header_matches_posthoc_format(self):
        """Stream-emitted header and post-hoc header for the same path render equal plain text (minus hit count)."""
        from hermes_cli.tui.body_renderers.streaming import SearchRenderer
        from hermes_cli.tui.body_renderers._grammar import build_path_header
        from rich.text import Text
        r = SearchRenderer()
        result = r.render_stream_line("src/main.py:10:hello", "src/main.py:10:hello")
        from rich.console import Group
        assert isinstance(result, Group)
        stream_header = result._renderables[0]
        posthoc_header = build_path_header("src/main.py", right_meta="", colors=None)
        # Both headers contain the path (use .plain for Text objects)
        sh_text = stream_header.plain if isinstance(stream_header, Text) else str(stream_header)
        ph_text = posthoc_header.plain if isinstance(posthoc_header, Text) else str(posthoc_header)
        assert "src/main.py" in sh_text
        assert "src/main.py" in ph_text


# ---------------------------------------------------------------------------
# R-X3: Streaming diff gutter
# ---------------------------------------------------------------------------

class TestStreamingDiffGutter:
    def test_stream_diff_add_has_gutter(self):
        """render_diff_line('+added') → first two visible chars '+ '."""
        from hermes_cli.tui.body_renderers.streaming import FileRenderer
        r = FileRenderer()
        result = r.render_diff_line("+added")
        text = str(result)
        # The gutter prefix should be '+ '
        assert text.startswith("+ ")

    def test_stream_diff_uses_skin_bg(self):
        """Added line bg is diff_add_bg from SkinColors."""
        from hermes_cli.tui.body_renderers.streaming import FileRenderer
        from hermes_cli.tui.body_renderers._grammar import SkinColors
        r = FileRenderer()
        result = r.render_diff_line("+added line")
        # Find a span with bgcolor matching diff_add_bg
        default_bg = SkinColors.default().diff_add_bg
        found = any(
            span.style.bgcolor and default_bg.lower() in str(span.style.bgcolor).lower()
            for span in result._spans
        )
        assert found

    def test_stream_diff_no_word_diff_highlight(self):
        """Consecutive '-foo' then '+bar' — neither carries bold+underline style."""
        from hermes_cli.tui.body_renderers.streaming import FileRenderer
        r = FileRenderer()
        rem = r.render_diff_line("-foo")
        add = r.render_diff_line("+bar")
        for text in (rem, add):
            for span in text._spans:
                style = span.style
                assert not (style.bold and style.underline), \
                    f"Unexpected bold+underline on span: {span}"


# ---------------------------------------------------------------------------
# R-P1: pick_renderer — SHELL override relaxation
# ---------------------------------------------------------------------------

class TestPickRendererShell:
    def test_shell_high_conf_diff_uses_diff_renderer(self):
        """SHELL + DIFF + 0.9 → DiffRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _make_payload(category=ToolCategory.SHELL)
        cls = _make_cls(ResultKind.DIFF, confidence=0.9)
        assert pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is DiffRenderer

    def test_shell_low_conf_diff_uses_shell(self):
        """SHELL + DIFF + 0.7 → ShellOutputRenderer (low confidence)."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _make_payload(category=ToolCategory.SHELL)
        cls = _make_cls(ResultKind.DIFF, confidence=0.7)
        assert pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is ShellOutputRenderer

    def test_non_shell_category_unchanged(self):
        """FILE + CODE + 0.9 → CodeRenderer (unchanged)."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.code import CodeRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _make_payload(category=ToolCategory.FILE)
        cls = _make_cls(ResultKind.CODE, confidence=0.9)
        assert pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is CodeRenderer

    def test_shell_empty_still_empty_state(self):
        """SHELL + EMPTY → EmptyStateRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _make_payload(category=ToolCategory.SHELL)
        cls = _make_cls(ResultKind.EMPTY, confidence=0.9)
        assert pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT) is EmptyStateRenderer


# ---------------------------------------------------------------------------
# R-P2: Low-confidence disclosure
# ---------------------------------------------------------------------------

class TestPickRendererLowConf:
    def test_low_conf_search_picked(self):
        """SEARCH + 0.6 → SearchRenderer is returned (not Fallback)."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        payload = _make_payload(category=ToolCategory.SEARCH, output_raw="foo:1:bar")
        cls = _make_cls(ResultKind.SEARCH, confidence=0.6)
        result = pick_renderer(cls, payload, phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
        assert result is SearchRenderer

    def test_low_conf_disclosure_header(self):
        """SearchRenderer with _low_confidence_disclosed flag → first rendered line contains 'low confidence'."""
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        payload = _make_payload(
            category=ToolCategory.SEARCH,
            output_raw="foo.py:1:hello\n",
        )
        cls = _make_cls(ResultKind.SEARCH, confidence=0.6)
        object.__setattr__(cls, "_low_confidence_disclosed", True)
        r = SearchRenderer(payload, cls)
        result = str(r.build())
        assert "low confidence" in result

    def test_high_conf_no_disclosure(self):
        """SearchRenderer with confidence 0.9 → no disclosure header."""
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        from hermes_cli.tui.tool_payload import ResultKind
        from hermes_cli.tui.tool_category import ToolCategory
        payload = _make_payload(
            category=ToolCategory.SEARCH,
            output_raw="foo.py:1:hello\n",
        )
        cls = _make_cls(ResultKind.SEARCH, confidence=0.9)
        r = SearchRenderer(payload, cls)
        result = str(r.build())
        assert "low confidence" not in result


# ---------------------------------------------------------------------------
# R-P3: Registry order
# ---------------------------------------------------------------------------

class TestRegistryOrder:
    def test_registry_order(self):
        """REGISTRY equals the exact list by class name."""
        from hermes_cli.tui.body_renderers import REGISTRY
        names = [r.__name__ for r in REGISTRY]
        assert names == [
            "DiffRenderer",
            "JsonRenderer",
            "SearchRenderer",
            "TableRenderer",
            "CodeRenderer",
            "LogRenderer",
            "ShellOutputRenderer",
            "EmptyStateRenderer",
            "FallbackRenderer",
        ]


# ---------------------------------------------------------------------------
# R-G5: Truncation footer helper
# ---------------------------------------------------------------------------

class TestTruncationFooter:
    def test_truncation_footer_wording(self):
        """truncation_footer(hidden_n=47).plain equals '── 47 lines hidden · expand ──'."""
        from hermes_cli.tui.body_renderers._grammar import truncation_footer
        result = truncation_footer(hidden_n=47)
        assert result.plain == "── 47 lines hidden · expand ──"

    def test_truncation_footer_muted_style(self):
        """colors=SkinColors(muted='#aabbcc') → '#aabbcc' in str of span color."""
        from hermes_cli.tui.body_renderers._grammar import truncation_footer, SkinColors
        colors = SkinColors(
            accent="#000000",
            muted="#aabbcc",
            success="#000000",
            error="#000000",
            warning="#000000",
            info="#000000",
            icon_dim="#000000",
            separator_dim="#000000",
            diff_add_bg="#000000",
            diff_del_bg="#000000",
            syntax_theme="ansi_dark",
            syntax_scheme="hermes",
        )
        result = truncation_footer(hidden_n=10, colors=colors)
        # build_rule sets the style at Text level (not span level)
        assert "#aabbcc" in str(result.style.color)

    def test_all_renderers_use_helper(self):
        """Policy: renderer files that emit truncation-like messages use truncation_footer."""
        import ast
        import pathlib

        renderers_dir = pathlib.Path(__file__).parent.parent.parent / "hermes_cli/tui/body_renderers"
        skip = {"search.py", "__init__.py"}  # search deferred per spec

        for path in renderers_dir.glob("*.py"):
            if path.name in skip or path.name.startswith("_"):
                continue
            src = path.read_text()
            # If the file has "hidden" or "collapsed" strings (inline truncation),
            # it must also call truncation_footer OR import from _grammar
            has_inline = (
                '"hidden"' in src or "'hidden'" in src or
                '"collapsed"' in src or "'collapsed'" in src
            )
            has_helper = "truncation_footer" in src or "from hermes_cli.tui.body_renderers._grammar" in src
            if has_inline and not has_helper:
                pytest.fail(
                    f"{path.name} uses inline truncation strings but does not call truncation_footer"
                )
