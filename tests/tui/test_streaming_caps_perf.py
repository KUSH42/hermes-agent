"""Spec E — Buffer Caps + Perf (M1, M4, M9, M10).

Classes:
    TestM1BufferCaps       — 4 tests: footnote, citation, math, code-fence caps
    TestM4ReasoningReflow  — 3 tests: layout-reflow call counts in append_delta
    TestM9CopyableRichLog  — 3 tests: _render_width caching via on_resize / on_mount
    TestM10SearchRenderer  — 2 tests: _last_emitted_path reset in finalize
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """ResponseFlowEngine with a fully mocked panel."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine
    panel = MagicMock()
    panel.current_prose_log.return_value = MagicMock()
    panel.show_response_rule = MagicMock()
    return ResponseFlowEngine(panel=panel)


def _make_reasoning_panel():
    """ReasoningPanel with all Textual dependencies mocked out."""
    from hermes_cli.tui.widgets.message_panel import ReasoningPanel
    panel = ReasoningPanel.__new__(ReasoningPanel)
    log = MagicMock()
    log._deferred_renders = []
    panel._reasoning_log = log
    panel._live_buf = ""
    panel._plain_lines = []
    panel._reasoning_engine = None
    panel._live_line = MagicMock()
    panel.refresh = MagicMock()
    panel.call_after_refresh = MagicMock()
    panel.add_class = MagicMock()
    panel._gutter_line = lambda x: x
    return panel


# ---------------------------------------------------------------------------
# M1 — Buffer caps
# ---------------------------------------------------------------------------

class TestM1BufferCaps:
    def test_footnote_buffer_cap(self):
        """Feed 600 unique footnote definitions; only first 500 retained, warning logged."""
        from hermes_cli.tui.response_flow import _MAX_FOOTNOTES
        eng = _make_engine()

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            for i in range(600):
                eng._handle_footnote(f"[^{i}]: body {i}")

        assert len(eng._footnote_defs) == _MAX_FOOTNOTES
        assert mock_log.warning.call_count >= 1
        # Warning message references the cap constant
        warn_msg = mock_log.warning.call_args_list[0].args[0]
        assert "footnote" in warn_msg.lower() or "cap" in warn_msg.lower()

    def test_citation_buffer_cap(self):
        """Feed 600 unique citation entries; only first 500 retained, warning logged."""
        from hermes_cli.tui.response_flow import _MAX_CITATIONS
        eng = _make_engine()

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            for i in range(1, 601):
                # CITE format: [CITE:N Title — https://url]
                eng._handle_citation_line(
                    f"[CITE:{i} Title {i} — https://example.com/{i}]"
                )

        assert len(eng._cite_entries) == _MAX_CITATIONS
        assert mock_log.warning.call_count >= 1
        warn_msg = mock_log.warning.call_args_list[0].args[0]
        assert "citation" in warn_msg.lower() or "cap" in warn_msg.lower()

    def test_math_buffer_cap_resets_state(self):
        """Feed 10001 math lines; state machine moves to NORMAL and buffer is cleared."""
        from hermes_cli.tui.response_flow import _MAX_MATH_LINES
        eng = _make_engine()
        eng._state = "IN_MATH"

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            for i in range(_MAX_MATH_LINES + 1):
                eng._dispatch_non_normal_state(f"x_{i} = {i}")

        assert eng._state == "NORMAL"
        assert eng._math_lines == []
        assert mock_log.warning.call_count >= 1
        warn_msg = mock_log.warning.call_args_list[0].args[0]
        assert "math" in warn_msg.lower()

    def test_code_fence_buffer_cap(self):
        """Feed 600 numbered lines; only first 500 buffered, overflow logged at debug."""
        from hermes_cli.tui.response_flow import _MAX_CODE_FENCE_BUFFER
        eng = _make_engine()

        with patch("hermes_cli.tui.response_flow._log") as mock_log:
            for i in range(1, 601):
                # Pattern must match _NUMBERED_LINE_RE: r"^\s*\d{1,3}\s*\|\s+\S"
                line = f"  {i % 1000} | code line {i}"
                eng._commit_prose_line(line, line)

        assert len(eng._code_fence_buffer) == _MAX_CODE_FENCE_BUFFER
        # Debug log called for overflow lines
        assert mock_log.debug.call_count >= 1


# ---------------------------------------------------------------------------
# M4 — ReasoningPanel.append_delta reflow
# ---------------------------------------------------------------------------

class TestM4ReasoningReflow:
    def test_append_delta_no_layout_reflow_for_plain_text(self):
        """Plain text deltas must call refresh() not refresh(layout=True)."""
        panel = _make_reasoning_panel()
        # _deferred_renders empty → no layout reflow expected
        panel._reasoning_log._deferred_renders = []

        from hermes_cli.tui.widgets.message_panel import ReasoningPanel
        for _ in range(10):
            ReasoningPanel.append_delta(panel, "word ")

        # refresh(layout=True) must never be called
        for c in panel.refresh.call_args_list:
            assert c != call(layout=True), (
                "refresh(layout=True) called on plain-text delta path"
            )
        # Plain refresh() called at least once per delta
        plain_calls = [c for c in panel.refresh.call_args_list if c == call()]
        assert len(plain_calls) >= 10

    def test_append_delta_uses_layout_reflow_when_deferred_renders_pending(self):
        """When _deferred_renders is non-empty, refresh(layout=True) is called."""
        panel = _make_reasoning_panel()
        panel._reasoning_log._deferred_renders = [object()]  # non-empty

        from hermes_cli.tui.widgets.message_panel import ReasoningPanel
        ReasoningPanel.append_delta(panel, "word ")

        layout_calls = [c for c in panel.refresh.call_args_list if c == call(layout=True)]
        assert len(layout_calls) >= 1

    def test_perf_layout_reflow_count_under_streaming(self):
        """Feed 100 plain deltas; layout-reflow count must be <= 5."""
        panel = _make_reasoning_panel()
        panel._reasoning_log._deferred_renders = []  # always empty → no layout reflow

        from hermes_cli.tui.widgets.message_panel import ReasoningPanel
        for _ in range(100):
            ReasoningPanel.append_delta(panel, "tok ")

        layout_calls = [c for c in panel.refresh.call_args_list if c == call(layout=True)]
        assert len(layout_calls) <= 5, (
            f"Too many layout reflows: {len(layout_calls)} (threshold: 5)"
        )


# ---------------------------------------------------------------------------
# M9 — CopyableRichLog._render_width caching
# ---------------------------------------------------------------------------

class TestM9CopyableRichLog:
    def _make_log(self):
        """CopyableRichLog with minimal mocking (no Textual app needed)."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        log = CopyableRichLog.__new__(CopyableRichLog)
        log._render_width = None
        log._plain_lines = []
        log._line_links = []
        return log

    def _make_resize_event(self, width: int):
        from textual import events
        from textual.geometry import Size
        return events.Resize(Size(width, 24), Size(width, 24))

    def test_render_width_captured_on_resize(self):
        """on_resize sets _render_width to the event's width."""
        log = self._make_log()
        assert log._render_width is None

        event = self._make_resize_event(80)
        log.on_resize(event)

        assert log._render_width == 80

    def test_render_width_updates_on_second_resize(self):
        """on_resize always overwrites _render_width with the latest width."""
        log = self._make_log()
        log.on_resize(self._make_resize_event(80))
        assert log._render_width == 80

        log.on_resize(self._make_resize_event(120))
        assert log._render_width == 120

    def test_write_before_layout_defers_once(self):
        """write() with _render_width=None and not _deferred defers via call_after_refresh."""
        from hermes_cli.tui.widgets.renderers import CopyableRichLog
        from rich.text import Text
        from textual.geometry import Region, Size

        log = CopyableRichLog.__new__(CopyableRichLog)
        log._render_width = None
        log._plain_lines = []
        log._line_links = []
        log.call_after_refresh = MagicMock()

        # scrollable_content_region and size are Textual properties; patch via type
        with (
            patch.object(
                type(log), "scrollable_content_region",
                new_callable=PropertyMock, return_value=Region(0, 0, 0, 0),
            ),
            patch.object(
                type(log), "size",
                new_callable=PropertyMock, return_value=Size(0, 0),
            ),
        ):
            content = Text("hello")
            result = log.write(content)

        # Should have deferred and returned self without calling super().write()
        assert log.call_after_refresh.call_count == 1
        assert result is log

        # Second call with _deferred=True must NOT defer again
        app_mock = MagicMock()
        app_mock.size.width = 80
        with (
            patch.object(
                type(log), "scrollable_content_region",
                new_callable=PropertyMock, return_value=Region(0, 0, 0, 0),
            ),
            patch.object(
                type(log), "size",
                new_callable=PropertyMock, return_value=Size(0, 0),
            ),
            patch.object(type(log), "app", new_callable=PropertyMock, return_value=app_mock),
            patch.object(type(log).__mro__[1], "write", return_value=log),
        ):
            log.write(content, _deferred=True)

        assert log.call_after_refresh.call_count == 1  # no second defer


# ---------------------------------------------------------------------------
# M10 — StreamingSearchRenderer._last_emitted_path cross-call leak
# ---------------------------------------------------------------------------

class TestM10SearchRendererReset:
    def _make_renderer(self):
        from hermes_cli.tui.body_renderers.streaming import StreamingSearchRenderer
        return StreamingSearchRenderer()

    def test_search_renderer_emits_path_header_on_first_call(self):
        """render_stream_line emits a path header for the first unique path."""
        from hermes_cli.tui.body_renderers._grammar import build_path_header
        renderer = self._make_renderer()

        result = renderer.render_stream_line(
            "src/foo.py:1: match", "src/foo.py:1: match"
        )
        assert renderer._last_emitted_path == "src/foo.py"

    def test_search_renderer_resets_path_between_calls(self):
        """finalize resets _last_emitted_path so the next call re-emits path headers."""
        renderer = self._make_renderer()

        # First search call: stream a line, then finalize
        renderer.render_stream_line("src/foo.py:1: hit", "src/foo.py:1: hit")
        assert renderer._last_emitted_path == "src/foo.py"
        renderer.finalize(["src/foo.py:1: hit"])

        # After finalize, path must be reset
        assert renderer._last_emitted_path is None

        # Second search call on same instance: path header must be re-emitted
        renderer.render_stream_line("src/foo.py:2: next", "src/foo.py:2: next")
        # If state leaked, _last_emitted_path would still be "src/foo.py" and
        # the header would be suppressed. With the fix it was reset → header emitted.
        assert renderer._last_emitted_path == "src/foo.py"
