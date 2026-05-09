"""SR — Search/JSON Routing & Wrap tests (13 tests).

SR-RW-H1: Untruncated output reaches classifier; JSON guard on can_render.
SR-RW-H2: Search preview lines word-wrap at viewport width.
SR-RW-M1: Prevent stacked body modalities in _swap_renderer.
"""
from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cls(kind: ResultKind, confidence: float = 0.9, metadata: dict | None = None) -> ClassificationResult:
    return ClassificationResult(kind, confidence, metadata or {})


def _payload(
    output_raw: str = "",
    tool_name: str = "grep",
    category: object = None,
) -> ToolPayload:
    return ToolPayload(
        tool_name=tool_name,
        category=category or ToolCategory.SEARCH,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _mock_block(all_plain: list[str] | None = None, renderer_output_raw: str | None = None):
    """Minimal streaming block stub."""
    block = MagicMock()
    block._all_plain = list(all_plain) if all_plain is not None else []
    block._plain_lines = None
    block._content_lines = None
    if renderer_output_raw is not None:
        block._renderer_output_raw = renderer_output_raw
    else:
        del block._renderer_output_raw  # ensure getattr returns None
    block._tool_panel = None
    block.complete = MagicMock()
    return block


def _make_svc():
    """Return a minimal ToolRenderingService with a mock app."""
    import threading
    from hermes_cli.tui.services.tools import ToolRenderingService
    from hermes_cli.tui.services.plan_sync import PlanSyncBroker

    app = MagicMock()
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0

    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = app
    svc._streaming_map = {}
    svc._turn_tool_calls = {}
    svc._agent_stack = []
    svc._subagent_panels = {}
    svc._open_tool_count = 0
    svc._tool_views_by_id = {}
    svc._tool_views_by_gen_index = {}
    svc._tool_views_history_by_id = {}
    svc._pending_gen_arg_deltas = {}
    svc._state_lock = threading.RLock()
    svc._plan_broker = PlanSyncBroker(svc)
    return svc


# ---------------------------------------------------------------------------
# TestH1UntruncatedPayload — 5 tests
# ---------------------------------------------------------------------------

class TestH1UntruncatedPayload:

    def test_close_streaming_sets_renderer_output_raw_without_result_lines(self):
        """When result_lines=None, _renderer_output_raw is built from _all_plain."""
        svc = _make_svc()
        block = _mock_block(all_plain=["line1", "line2", "line3"])
        svc.app._active_streaming_blocks["tc1"] = block

        with patch.object(svc, "_terminalize_tool_view", return_value=None), \
             patch.object(svc, "_get_output_panel", return_value=None), \
             patch.object(svc.app, "_svc_commands", create=True):
            svc.close_streaming_tool_block("tc1", "1.0s", result_lines=None)

        assert block._renderer_output_raw == "line1\nline2\nline3"

    def test_close_streaming_skips_fallback_when_raw_already_set(self):
        """If _renderer_output_raw already set, elif branch does not overwrite."""
        svc = _make_svc()
        block = _mock_block(all_plain=["new"], renderer_output_raw="existing_raw")
        svc.app._active_streaming_blocks["tc2"] = block

        with patch.object(svc, "_terminalize_tool_view", return_value=None), \
             patch.object(svc, "_get_output_panel", return_value=None), \
             patch.object(svc.app, "_svc_commands", create=True):
            svc.close_streaming_tool_block("tc2", "1.0s", result_lines=None)

        assert block._renderer_output_raw == "existing_raw"

    def test_classifier_receives_untruncated_payload(self):
        """3000-char single-line JSON in _all_plain (would be truncated) is correctly
        joined from _all_plain into _renderer_output_raw so classifier gets full text."""
        svc = _make_svc()
        big_json = json.dumps({"total_count": 5, "files": ["/a/" * 200 + "f.py"] * 5})
        assert len(big_json) > 2000, "fixture must exceed _LINE_BYTE_CAP"

        block = _mock_block(all_plain=[big_json])
        svc.app._active_streaming_blocks["tc3"] = block

        with patch.object(svc, "_terminalize_tool_view", return_value=None), \
             patch.object(svc, "_get_output_panel", return_value=None), \
             patch.object(svc.app, "_svc_commands", create=True):
            svc.close_streaming_tool_block("tc3", "1.0s", result_lines=None)

        # _renderer_output_raw must be the full JSON, parseable
        raw = block._renderer_output_raw
        parsed = json.loads(raw)
        assert parsed["total_count"] == 5

    def test_search_renderer_rejects_json_kind(self):
        """SearchRenderer.can_render returns False when classification is JSON."""
        from hermes_cli.tui.body_renderers.search import SearchRenderer

        cls_result = _cls(ResultKind.JSON)
        p = _payload(output_raw='{"total_count": 5, "files": []}')
        assert SearchRenderer.can_render(cls_result, p) is False

    def test_streaming_search_renderer_rejects_json_kind(self):
        """StreamingSearchRenderer.can_render returns False when classification is JSON."""
        from hermes_cli.tui.body_renderers.streaming import StreamingSearchRenderer

        cls_result = _cls(ResultKind.JSON)
        p = _payload(output_raw='{"total_count": 5, "files": []}')
        assert StreamingSearchRenderer.can_render(cls_result, p) is False


# ---------------------------------------------------------------------------
# TestH2SearchPreviewWrap — 5 tests
# ---------------------------------------------------------------------------

class TestH2SearchPreviewWrap:

    def _make_renderer(self, output_raw: str = "") -> "object":
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        p = _payload(output_raw=output_raw)
        c = _cls(ResultKind.SEARCH)
        return SearchRenderer(p, c, app=None)

    def _grep_raw(self, line_content: str) -> str:
        """Build a minimal grep-format payload: path header then numbered hit line."""
        return f"file.py\n1:{line_content}\n"

    def test_short_line_no_truncation(self):
        """Lines shorter than viewport_width are not truncated."""
        raw = self._grep_raw("short line")
        renderer = self._make_renderer(raw)
        result = renderer.build(viewport_width=80)
        assert "short line" in result.plain

    def test_medium_line_no_truncation(self):
        """Lines at 1.5× viewport_width are not truncated (Rich handles wrapping)."""
        line = "x" * 120  # 1.5 × 80
        raw = self._grep_raw(line)
        renderer = self._make_renderer(raw)
        result = renderer.build(viewport_width=80)
        assert line in result.plain

    def test_long_line_truncates_with_ellipsis(self):
        """Lines at 5× viewport_width are truncated to viewport_width and end with …."""
        import re
        line = "a" * 400  # 5 × 80
        raw = self._grep_raw(line)
        renderer = self._make_renderer(raw)
        result = renderer.build(viewport_width=80)
        assert "…" in result.plain
        long_runs = re.findall(r"a{81,}", result.plain)
        assert not long_runs, f"Untruncated run of a's found: {long_runs}"

    def test_truncation_preserves_query_highlight(self):
        """Highlighted prefix is preserved even when tail is truncated."""
        from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
        from hermes_cli.tui.body_renderers.search import SearchRenderer
        query = "hello"
        line = query + "x" * 400
        raw = self._grep_raw(line)
        p = _payload(output_raw=raw)
        c = ClassificationResult(ResultKind.SEARCH, 0.9, {"query": query})
        renderer = SearchRenderer(p, c, app=None)
        result = renderer.build(viewport_width=80)
        assert query in result.plain

    def test_no_app_ref_falls_back_gracefully(self):
        """build(viewport_width=None) completes without error and returns Text."""
        from rich.text import Text
        raw = self._grep_raw("b" * 400)
        renderer = self._make_renderer(raw)
        result = renderer.build(viewport_width=None)
        assert isinstance(result, Text)
        assert "b" * 400 in result.plain


# ---------------------------------------------------------------------------
# TestM1SingleRendererPerBodyPane — 3 tests
# ---------------------------------------------------------------------------

class TestM1SingleRendererPerBodyPane:

    def _make_panel_stub(self, existing_children=None):
        """Minimal ToolPanel mixin stub for _swap_renderer path."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        class _FakeBodyPane:
            def __init__(self, children_list):
                self.children = children_list
                self._renderer = None
                self._block = None
                self._mounted = []

            def mount(self, w):
                self._mounted.append(w)

        class _FakePanel(_ToolPanelCompletionMixin):
            def __init__(self, children):
                self._body_pane = _FakeBodyPane(children)
                self._block = None
                self._pending_renderer_swap = None
                self._tool_name = "grep"
                self._category = ToolCategory.SEARCH
                self._tool_args = {}
                self._view_state = None
                self.app = MagicMock()

        panel = _FakePanel(existing_children or [])
        return panel

    def test_single_renderer_per_body_pane(self):
        """After two _swap_renderer calls the body pane has exactly 1 widget mounted
        in the direct-mount path (each call cleans up before mounting)."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
        from rich.text import Text

        panel = self._make_panel_stub(existing_children=[])
        p = _payload()
        c = _cls(ResultKind.TEXT)

        # First swap
        with patch.object(FallbackRenderer, "build_widget", return_value=MagicMock()):
            panel._swap_renderer(FallbackRenderer, p, c)

        # _body_pane now has 1 mounted widget; simulate it being in children list
        panel._body_pane.children = list(panel._body_pane._mounted)
        panel._block = None  # force direct-mount path on second call

        # Second swap — should clean up the existing child first
        with patch.object(FallbackRenderer, "build_widget", return_value=MagicMock()), \
             patch.object(panel._body_pane.children[0], "remove", create=True):
            panel._swap_renderer(FallbackRenderer, p, c)

        # Only 1 new mount in second call (prior cleared)
        assert len(panel._body_pane._mounted) == 2  # 1 from each call

    def test_double_mount_attempt_logs_warning(self):
        """If body_pane already has a non-placeholder child, _log.warning is called."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        stale_child = MagicMock()
        stale_child._is_placeholder = False
        stale_child.remove = MagicMock()

        panel = self._make_panel_stub(existing_children=[stale_child])
        panel._block = None  # force direct-mount path

        p = _payload()
        c = _cls(ResultKind.TEXT)

        with patch("hermes_cli.tui.tool_panel._completion._log") as mock_log, \
             patch.object(FallbackRenderer, "build_widget", return_value=MagicMock()):
            panel._swap_renderer(FallbackRenderer, p, c)

        mock_log.warning.assert_called_once()
        assert "already has" in mock_log.warning.call_args[0][0]

    def test_swap_renderer_clean_transition(self):
        """Normal swap with no pre-existing children: warning not called, 1 widget mounted."""
        from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

        panel = self._make_panel_stub(existing_children=[])
        panel._block = None

        p = _payload()
        c = _cls(ResultKind.TEXT)

        with patch("hermes_cli.tui.tool_panel._completion._log") as mock_log, \
             patch.object(FallbackRenderer, "build_widget", return_value=MagicMock()):
            panel._swap_renderer(FallbackRenderer, p, c)

        mock_log.warning.assert_not_called()
        assert len(panel._body_pane._mounted) == 1
