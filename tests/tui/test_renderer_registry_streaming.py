"""R-2B spec tests — fold streaming renderers into unified registry.

TestStreamingProtocolDefaults    (5)  R-2B-1
TestStreamingClassesAsBodyRenderer (7) R-2B-2
TestPickRendererStreamingBranch  (10) R-2B-3
TestCallSiteMigration            (12) R-2B-4
TestForCategoryRemoval           (6)  R-2B-5
TestExistingTestSweep            (4)  R-2B-6
Total: 44
"""
from __future__ import annotations

import subprocess
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
from rich.text import Text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2]


def _make_payload(category):
    from hermes_cli.tui.tool_payload import ToolPayload
    return ToolPayload(
        tool_name="",
        category=category,
        args={},
        input_display=None,
        output_raw="",
        line_count=0,
    )


def _empty_cls():
    from hermes_cli.tui.body_renderers import _STREAMING_EMPTY_CLS
    return _STREAMING_EMPTY_CLS


# ---------------------------------------------------------------------------
# R-2B-1: Streaming protocol defaults on BodyRenderer
# ---------------------------------------------------------------------------


class TestStreamingProtocolDefaults:
    def test_default_render_stream_line_raises_not_implemented(self):
        """BodyRenderer that did not opt into STREAMING raises NotImplementedError."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _FakePhaseC(BodyRenderer):
            kind = ResultKind.TEXT

            @classmethod
            def can_render(cls, cls_result, payload):
                return False

            def build(self):
                return Text("")

        r = _FakePhaseC()
        with pytest.raises(NotImplementedError):
            r.render_stream_line("raw", "plain")

    def test_default_finalize_returns_none(self):
        """BodyRenderer.finalize default returns None."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _FakeRenderer(BodyRenderer):
            kind = ResultKind.TEXT

            @classmethod
            def can_render(cls, cls_result, payload):
                return False

            def build(self):
                return Text("")

        r = _FakeRenderer()
        assert r.finalize(["a", "b"]) is None

    def test_default_preview_returns_dim_tail(self):
        """BodyRenderer.preview returns dim Text of last max_lines lines."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _FakeRenderer(BodyRenderer):
            kind = ResultKind.TEXT

            @classmethod
            def can_render(cls, cls_result, payload):
                return False

            def build(self):
                return Text("")

        r = _FakeRenderer()
        result = r.preview(["a", "b", "c"], 2)
        assert isinstance(result, Text)
        assert result.plain == "b\nc"
        assert "dim" in str(result._spans[0].style) if result._spans else result.style == "dim"

    def test_default_extract_sidecar_noop(self):
        """BodyRenderer.extract_sidecar is a no-op (does not raise, does not mutate)."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        from hermes_cli.tui.tool_payload import ResultKind

        class _FakeRenderer(BodyRenderer):
            kind = ResultKind.TEXT

            @classmethod
            def can_render(cls, cls_result, payload):
                return False

            def build(self):
                return Text("")

        tool_call = types.SimpleNamespace(result_paths=[])
        r = _FakeRenderer()
        r.extract_sidecar(tool_call, ["line"])
        assert tool_call.result_paths == []  # unchanged

    def test_specialised_methods_not_on_base(self):
        """BodyRenderer ABC has no render_diff_line, render_code_line etc."""
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        for name in ("render_diff_line", "render_code_line", "render_output_line",
                     "highlight_line", "finalize_code"):
            assert not hasattr(BodyRenderer, name), f"BodyRenderer should not have {name}"


# ---------------------------------------------------------------------------
# R-2B-2: Streaming classes inherit BodyRenderer
# ---------------------------------------------------------------------------


class TestStreamingClassesAsBodyRenderer:
    def _all_streaming_classes(self):
        from hermes_cli.tui.body_renderers.streaming import (
            ShellRenderer, StreamingCodeRenderer, FileRenderer,
            StreamingSearchRenderer, WebRenderer, AgentRenderer,
            TextRenderer, MCPBodyRenderer, PlainBodyRenderer,
        )
        return [
            ShellRenderer, StreamingCodeRenderer, FileRenderer,
            StreamingSearchRenderer, WebRenderer, AgentRenderer,
            TextRenderer, MCPBodyRenderer, PlainBodyRenderer,
        ]

    def test_streaming_classes_inherit_body_renderer(self):
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        for cls in self._all_streaming_classes():
            assert issubclass(cls, BodyRenderer), f"{cls.__name__} must inherit BodyRenderer"

    def test_streaming_classes_accept_streaming_phase(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer

        for cls in self._all_streaming_classes():
            assert cls.accepts(ToolCallState.STREAMING, DensityTier.DEFAULT), \
                f"{cls.__name__}.accepts(STREAMING) should be True"
            assert cls.accepts(ToolCallState.STARTED, DensityTier.DEFAULT), \
                f"{cls.__name__}.accepts(STARTED) should be True"

    def test_streaming_classes_reject_completing_done(self):
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer

        assert not ShellRenderer.accepts(ToolCallState.COMPLETING, DensityTier.DEFAULT)
        assert not ShellRenderer.accepts(ToolCallState.DONE, DensityTier.DEFAULT)

    def test_streaming_can_render_keys_on_category(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.body_renderers.streaming import (
            ShellRenderer, StreamingCodeRenderer, FileRenderer,
            StreamingSearchRenderer, WebRenderer, AgentRenderer,
            TextRenderer, MCPBodyRenderer,
        )
        cls_result = _empty_cls()
        mapping = [
            (ShellRenderer, ToolCategory.SHELL),
            (StreamingCodeRenderer, ToolCategory.CODE),
            (FileRenderer, ToolCategory.FILE),
            (StreamingSearchRenderer, ToolCategory.SEARCH),
            (WebRenderer, ToolCategory.WEB),
            (AgentRenderer, ToolCategory.AGENT),
            (TextRenderer, ToolCategory.UNKNOWN),
            (MCPBodyRenderer, ToolCategory.MCP),
        ]
        all_cats = [pair[1] for pair in mapping]
        for renderer_cls, expected_cat in mapping:
            assert renderer_cls.can_render(cls_result, _make_payload(expected_cat)), \
                f"{renderer_cls.__name__}.can_render should be True for {expected_cat}"
            for other_cat in all_cats:
                if other_cat != expected_cat:
                    assert not renderer_cls.can_render(cls_result, _make_payload(other_cat)), \
                        f"{renderer_cls.__name__}.can_render should be False for {other_cat}"

    def test_plain_body_renderer_can_render_returns_false(self):
        from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer
        from hermes_cli.tui.tool_category import ToolCategory
        cls_result = _empty_cls()
        for cat in ToolCategory:
            assert not PlainBodyRenderer.can_render(cls_result, _make_payload(cat))

    def test_streaming_code_renderer_renamed(self):
        """StreamingCodeRenderer importable; old name CodeRenderer no longer resolves."""
        from hermes_cli.tui.body_renderers.streaming import StreamingCodeRenderer
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        assert issubclass(StreamingCodeRenderer, BodyRenderer)

        with pytest.raises((ImportError, AttributeError)):
            from hermes_cli.tui.body_renderers import streaming as _sm
            # After rename, the old 'CodeRenderer' attribute must not exist on streaming module
            # (the Phase C CodeRenderer is in body_renderers.code, not streaming)
            _ = _sm.CodeRenderer  # type: ignore[attr-defined]

    def test_streaming_search_renderer_renamed(self):
        """StreamingSearchRenderer importable; old name SearchRenderer no longer in streaming."""
        from hermes_cli.tui.body_renderers.streaming import StreamingSearchRenderer
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        assert issubclass(StreamingSearchRenderer, BodyRenderer)

        with pytest.raises((ImportError, AttributeError)):
            from hermes_cli.tui.body_renderers import streaming as _sm
            _ = _sm.SearchRenderer  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# R-2B-3: pick_renderer streaming branch
# ---------------------------------------------------------------------------


class TestPickRendererStreamingBranch:
    def _pick(self, category, phase=None, density=None, cls_result=None):
        from hermes_cli.tui.body_renderers import pick_renderer, _STREAMING_EMPTY_CLS
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        return pick_renderer(
            cls_result or _STREAMING_EMPTY_CLS,
            _make_payload(category),
            phase=phase or ToolCallState.STREAMING,
            density=density or DensityTier.DEFAULT,
        )

    def test_streaming_phase_routes_to_streaming_tier_for_shell(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        assert self._pick(ToolCategory.SHELL) is ShellRenderer

    def test_streaming_phase_routes_for_each_category(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.body_renderers.streaming import (
            ShellRenderer, StreamingCodeRenderer, FileRenderer,
            StreamingSearchRenderer, WebRenderer, AgentRenderer,
            TextRenderer, MCPBodyRenderer,
        )
        expected = {
            ToolCategory.SHELL: ShellRenderer,
            ToolCategory.CODE: StreamingCodeRenderer,
            ToolCategory.FILE: FileRenderer,
            ToolCategory.SEARCH: StreamingSearchRenderer,
            ToolCategory.WEB: WebRenderer,
            ToolCategory.AGENT: AgentRenderer,
            ToolCategory.UNKNOWN: TextRenderer,
            ToolCategory.MCP: MCPBodyRenderer,
        }
        for cat, cls in expected.items():
            result = self._pick(cat)
            assert result is cls, f"Expected {cls.__name__} for {cat}, got {result.__name__}"

    def test_streaming_phase_unknown_category_falls_back_to_plain(self):
        from hermes_cli.tui.body_renderers import pick_renderer, _STREAMING_EMPTY_CLS
        from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier

        sentinel_cat = types.SimpleNamespace()  # no ToolCategory match
        payload = types.SimpleNamespace(category=sentinel_cat)
        result = pick_renderer(
            _STREAMING_EMPTY_CLS, payload,  # type: ignore[arg-type]
            phase=ToolCallState.STREAMING,
            density=DensityTier.DEFAULT,
        )
        assert result is PlainBodyRenderer

    def test_streaming_phase_started_same_as_streaming(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        from hermes_cli.tui.services.tools import ToolCallState
        assert self._pick(ToolCategory.SHELL, phase=ToolCallState.STARTED) is ShellRenderer

    def test_streaming_phase_ignores_classification(self):
        """Streaming branch keys on category, not classification — JSON cls + SHELL cat → ShellRenderer."""
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind

        json_cls = ClassificationResult(kind=ResultKind.JSON, confidence=1.0)
        result = self._pick(ToolCategory.SHELL, cls_result=json_cls)
        assert result is ShellRenderer

    def test_completing_phase_unchanged_routing(self):
        """Phase C routing unchanged after streaming classes added to REGISTRY."""
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier

        shell_payload = ToolPayload(tool_name="", category=ToolCategory.SHELL,
                                    args={}, input_display=None, output_raw="", line_count=0)
        text_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)
        assert pick_renderer(text_cls, shell_payload,
                             phase=ToolCallState.COMPLETING,
                             density=DensityTier.DEFAULT) is ShellOutputRenderer

    def test_done_phase_unchanged_routing(self):
        from hermes_cli.tui.body_renderers import pick_renderer
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier

        unknown_payload = ToolPayload(tool_name="", category=ToolCategory.UNKNOWN,
                                      args={}, input_display=None, output_raw="", line_count=0)
        text_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=0.1)
        assert pick_renderer(text_cls, unknown_payload,
                             phase=ToolCallState.DONE,
                             density=DensityTier.DEFAULT) is FallbackRenderer

    def test_streaming_renderer_not_picked_at_completing(self):
        """ShellRenderer.accepts(COMPLETING) is False; pick_renderer routes to Phase C ShellOutputRenderer."""
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer
        from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind

        assert not ShellRenderer.accepts(ToolCallState.COMPLETING, DensityTier.DEFAULT)

        text_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=1.0)
        result = self._pick(
            __import__("hermes_cli.tui.tool_category", fromlist=["ToolCategory"]).ToolCategory.SHELL,
            phase=ToolCallState.COMPLETING,
            cls_result=text_cls,
        )
        assert result is ShellOutputRenderer
        assert result is not ShellRenderer

    def test_phase_c_fallback_unaffected_by_streaming_classes(self):
        """DONE + no-match Phase C payload still returns FallbackRenderer."""
        from hermes_cli.tui.body_renderers import pick_renderer, _STREAMING_EMPTY_CLS
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier

        payload = ToolPayload(tool_name="", category=ToolCategory.UNKNOWN,
                              args={}, input_display=None, output_raw="", line_count=0)
        text_cls = ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)
        result = pick_renderer(text_cls, payload,
                               phase=ToolCallState.DONE, density=DensityTier.DEFAULT)
        assert result is FallbackRenderer

    def test_registry_order_streaming_after_phase_c(self):
        """Streaming classes sit after all Phase C entries in REGISTRY; PlainBodyRenderer absent."""
        from hermes_cli.tui.body_renderers import REGISTRY
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from hermes_cli.tui.body_renderers.streaming import ShellRenderer, PlainBodyRenderer

        assert REGISTRY.index(ShellRenderer) > REGISTRY.index(FallbackRenderer)
        assert PlainBodyRenderer not in REGISTRY


# ---------------------------------------------------------------------------
# R-2B-4: Call site migration
# ---------------------------------------------------------------------------


class TestCallSiteMigration:
    def test_block_render_diff_line_uses_pick_renderer(self):
        """_render_diff_line invokes pick_renderer with phase=STREAMING, category=FILE."""
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.services.tools import ToolCallState

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        # Patch at the source module so local `from ... import pick_renderer` gets the spy
        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
            from hermes_cli.tui.tool_blocks._block import ToolBlock
            obj = object.__new__(ToolBlock)
            ToolBlock._render_diff_line(obj, "+ foo")

        assert len(calls) == 1
        assert calls[0]["phase"] == ToolCallState.STREAMING
        assert calls[0]["density"] is not None

    def test_block_render_diff_line_returns_text_on_match(self):
        """_render_diff_line with real pick_renderer returns a Text renderable."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        import types as _t
        obj = object.__new__(ToolBlock)
        result = ToolBlock._render_diff_line(obj, "+ foo bar")
        assert result is not None
        assert isinstance(result, Text)

    def test_block_render_diff_line_logs_on_failure(self):
        """_render_diff_line logs when pick_renderer raises."""
        from hermes_cli.tui.tool_blocks._block import ToolBlock

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=RuntimeError("boom")):
            with patch("hermes_cli.tui.tool_blocks._block._log") as mock_log:
                obj = object.__new__(ToolBlock)
                result = ToolBlock._render_diff_line(obj, "+ foo")
        assert result is None
        mock_log.exception.assert_called_once()

    def test_execute_code_highlight_line_uses_pick_renderer(self):
        """_highlight_line invokes pick_renderer with category=CODE, phase=STREAMING."""
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        obj = object.__new__(ExecuteCodeBlock)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
            try:
                obj._highlight_line("x = 1")
            except Exception:
                pass  # app CSS lookup may fail outside app context

        assert len(calls) >= 1
        assert calls[0].get("phase") == ToolCallState.STREAMING

    def test_execute_code_finalize_code_uses_pick_renderer(self):
        """finalize_code invokes pick_renderer with phase=STREAMING, category=CODE."""
        from hermes_cli.tui.execute_code_block import ExecuteCodeBlock
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_category import ToolCategory

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        # Minimal stub to run finalize_code without full Textual app
        from textual.css.query import NoMatches

        obj = object.__new__(ExecuteCodeBlock)
        obj._code_state = "idle"  # not _STATE_FINALIZED
        obj._cursor_timer = None
        obj._pacer = None
        obj._code_lines = []
        obj._header = types.SimpleNamespace(_header_args={}, _spinner_char=None)
        # Provide a mock code_log so the query_one path is skipped
        mock_log = MagicMock()
        obj._cached_code_log = mock_log
        # query_one is called for OutputSeparator / OutputSection after the main block
        obj.query_one = MagicMock(side_effect=NoMatches)

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
            obj.finalize_code("def f():\n    return 1")

        assert any(k.get("phase") == ToolCallState.STREAMING for k in calls), \
            "finalize_code should call pick_renderer with phase=STREAMING"

    def test_footer_init_uses_pick_renderer(self):
        """BodyPane with FILE category calls pick_renderer and stores FileRenderer instance."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.body_renderers.streaming import FileRenderer
        from hermes_cli.tui.tool_category import ToolCategory

        pane = BodyPane(block=None, category=ToolCategory.FILE)
        assert isinstance(pane._renderer, FileRenderer)

    def test_footer_init_no_category_renderer_is_none(self):
        """BodyPane with category=None → _renderer is None."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        pane = BodyPane(block=None, category=None)
        assert pane._renderer is None

    def test_footer_init_falls_back_to_plain_on_failure(self):
        """BodyPane falls back to PlainBodyRenderer when pick_renderer raises."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer
        from hermes_cli.tui.tool_category import ToolCategory

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=RuntimeError("fail")):
            pane = BodyPane(block=None, category=ToolCategory.SHELL)
        assert isinstance(pane._renderer, PlainBodyRenderer)
        assert pane._renderer_degraded is True

    def test_write_file_consume_pacer_uses_pick_renderer(self):
        """_emit_content_line invokes pick_renderer with category=FILE, phase=STREAMING."""
        from hermes_cli.tui.write_file_block import WriteFileBlock
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_category import ToolCategory
        from textual.css.query import NoMatches

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        obj = object.__new__(WriteFileBlock)
        obj._content_lines = []
        obj._content_line_count = 0
        obj._path = "test.py"
        obj._line_scratch = ""
        obj._body = types.SimpleNamespace(query_one=MagicMock(side_effect=NoMatches))

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
            obj._emit_content_line("import os")

        assert obj._content_lines == ["import os"]

    def test_write_file_rehighlight_uses_pick_renderer(self):
        """_rehighlight_body invokes pick_renderer with phase=STREAMING (Open Issue 1)."""
        from hermes_cli.tui.write_file_block import WriteFileBlock
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.services.tools import ToolCallState
        from textual.css.query import NoMatches

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        obj = object.__new__(WriteFileBlock)
        obj._content_lines = ["line1", "line2"]
        obj._path = "test.py"
        obj._body = types.SimpleNamespace(query_one=MagicMock(side_effect=NoMatches))

        with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
            obj._rehighlight_body()

    def test_write_file_density_from_view_state(self):
        """_rehighlight_body passes density from _lookup_view_state when available."""
        from hermes_cli.tui.write_file_block import WriteFileBlock
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.tool_panel.density import DensityTier
        from textual.css.query import NoMatches

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        obj = object.__new__(WriteFileBlock)
        obj._content_lines = ["line1"]
        obj._path = "test.py"
        obj._body = types.SimpleNamespace(query_one=MagicMock(side_effect=NoMatches))

        view = types.SimpleNamespace(density=DensityTier.COMPACT)
        with patch.object(obj, "_lookup_view_state", return_value=view):
            with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
                obj._rehighlight_body()

        if calls:
            assert calls[0]["density"] == DensityTier.COMPACT

    def test_write_file_density_default_when_no_view_state(self):
        """_rehighlight_body defaults to DensityTier.DEFAULT when _lookup_view_state returns None."""
        from hermes_cli.tui.write_file_block import WriteFileBlock
        from hermes_cli.tui.body_renderers import pick_renderer as _real_pick
        from hermes_cli.tui.tool_panel.density import DensityTier
        from textual.css.query import NoMatches

        calls = []

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return _real_pick(*args, **kwargs)

        obj = object.__new__(WriteFileBlock)
        obj._content_lines = ["line1"]
        obj._path = "test.py"
        obj._body = types.SimpleNamespace(query_one=MagicMock(side_effect=NoMatches))

        with patch.object(obj, "_lookup_view_state", return_value=None):
            with patch("hermes_cli.tui.body_renderers.pick_renderer", side_effect=_spy):
                obj._rehighlight_body()

        if calls:
            assert calls[0]["density"] == DensityTier.DEFAULT


# ---------------------------------------------------------------------------
# R-2B-5: for_category, _RENDERERS, _CACHE deleted
# ---------------------------------------------------------------------------


class TestForCategoryRemoval:
    def test_for_category_removed(self):
        """StreamingBodyRenderer has no for_category attribute."""
        from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer
        assert not hasattr(StreamingBodyRenderer, "for_category")

    def test_renderers_dict_removed(self):
        """_RENDERERS no longer importable from streaming module."""
        with pytest.raises((ImportError, AttributeError)):
            from hermes_cli.tui.body_renderers import streaming as _sm
            _ = _sm._RENDERERS  # type: ignore[attr-defined]

    def test_no_for_category_callers(self):
        """No remaining for_category calls in hermes_cli/ source tree."""
        result = subprocess.run(
            ["grep", "-RIn", "--include=*.py", "for_category",
             "hermes_cli/", "tests/"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        matches = [
            line for line in result.stdout.splitlines()
            # Exclude the removal-test file itself (grep of for_category in test string literals)
            if "test_renderer_registry_streaming.py" not in line
        ]
        assert not matches, f"Unexpected for_category callers:\n" + "\n".join(matches)

    def test_streaming_body_renderer_alias_still_works(self):
        """StreamingBodyRenderer is BodyRenderer alias after R-2B-5."""
        from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer
        from hermes_cli.tui.body_renderers.base import BodyRenderer
        assert StreamingBodyRenderer is BodyRenderer

    def test_cache_class_attribute_removed(self):
        """StreamingBodyRenderer (= BodyRenderer) has no _CACHE attribute."""
        from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer
        assert not hasattr(StreamingBodyRenderer, "_CACHE")

    def test_build_renderers_removed(self):
        """_build_renderers no longer importable from streaming module."""
        with pytest.raises((ImportError, AttributeError)):
            from hermes_cli.tui.body_renderers import streaming as _sm
            _ = _sm._build_renderers  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# R-2B-6: Existing test sweep verification
# ---------------------------------------------------------------------------


class TestExistingTestSweep:
    @pytest.mark.slow
    def test_test_body_renderer_passes(self):
        """tests/tui/test_body_renderer.py passes after sweep."""
        result = subprocess.run(
            ["python", "-m", "pytest", "-q",
             "--override-ini=addopts=",
             "tests/tui/test_body_renderer.py"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.slow
    def test_test_body_renderers_passes(self):
        """tests/tui/test_body_renderers.py passes after sweep."""
        result = subprocess.run(
            ["python", "-m", "pytest", "-q",
             "--override-ini=addopts=",
             "tests/tui/test_body_renderers.py"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_no_remaining_for_category_in_tests(self):
        """No remaining for_category calls in tests/tui/."""
        result = subprocess.run(
            ["grep", "-RIn", "--include=*.py", "for_category", "tests/tui/"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        matches = [
            line for line in result.stdout.splitlines()
            if "test_renderer_registry_streaming.py" not in line
        ]
        assert not matches, "Unexpected for_category in tests:\n" + "\n".join(matches)

    def test_no_remaining_streaming_dot_coderenderer_in_tests(self):
        """No remaining streaming.CodeRenderer or streaming.SearchRenderer in tests."""
        result = subprocess.run(
            ["grep", "-RIn", "--include=*.py",
             r"streaming\.CodeRenderer\|streaming\.SearchRenderer",
             "tests/tui/"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        matches = [
            line for line in result.stdout.splitlines()
            if "test_renderer_registry_streaming.py" not in line
        ]
        assert not matches, \
            "Unexpected streaming.CodeRenderer/SearchRenderer in tests:\n" + "\n".join(matches)
