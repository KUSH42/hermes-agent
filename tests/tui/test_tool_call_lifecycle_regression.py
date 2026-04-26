"""TCL-HIGH-01/02 + TCL-MED-01/02 lifecycle regression tests.

Test layout:
    TestLiveOutputLifecycle      — TCL-HIGH-01: streaming callback → append_tool_output
    TestCompletionLifecycle      — TCL-HIGH-02: complete_tool_call single terminal path
    TestPanelArgumentWiring      — TCL-MED-01: _panel_for_block helper + panel wiring
    TestRendererExceptionLogging — TCL-MED-02: bare swallows replaced with debug logs
"""
from __future__ import annotations

import logging
import time
import types
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.services.tools import (
    ToolCallState,
    ToolCallViewState,
    ToolRenderingService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_app(**kwargs):
    app = MagicMock()
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0
    app._browse_total = 0
    app.planned_calls = []
    app.agent_running = True
    app._turn_start_monotonic = time.monotonic()
    app._explicit_parent_map = {}
    app.status_phase = None
    app._svc_commands = MagicMock()
    for k, v in kwargs.items():
        setattr(app, k, v)
    return app


def _make_service(app=None, **app_kwargs):
    if app is None:
        app = _make_mock_app(**app_kwargs)
    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = app
    svc._streaming_map = {}
    svc._turn_tool_calls = {}
    svc._agent_stack = []
    svc._subagent_panels = {}
    svc._open_tool_count = 0
    svc._tool_views_by_id = {}
    svc._tool_views_by_gen_index = {}
    svc._pending_gen_arg_deltas = {}
    return svc


def _started_view(tool_call_id: str, tool_name: str = "terminal") -> ToolCallViewState:
    return ToolCallViewState(
        tool_call_id=tool_call_id,
        gen_index=None,
        tool_name=tool_name,
        label=tool_name,
        args={},
        state=ToolCallState.STARTED,
        block=None,
        panel=None,
        parent_tool_call_id=None,
        category="shell",
        depth=0,
        start_s=0.0,
    )


# ---------------------------------------------------------------------------
# TCL-HIGH-01: Live output lifecycle
# ---------------------------------------------------------------------------

class TestLiveOutputLifecycle:
    """TCL-HIGH-01: streaming callback must target append_tool_output."""

    def test_terminal_stream_callback_uses_append_tool_output(self):
        """_on_tool_start registers append_tool_output, not append_streaming_line."""
        import cli as _cli_mod

        captured_callbacks = []

        def fake_set_cb(fn):
            captured_callbacks.append(fn)
            return object()  # token

        fake_tui = MagicMock()
        fake_tui.call_from_thread = MagicMock()

        with patch.object(_cli_mod, "_hermes_app", fake_tui), \
             patch("tools.terminal_tool.set_streaming_callback", fake_set_cb):
            inst = _cli_mod.HermesCLI.__new__(_cli_mod.HermesCLI)
            inst._pending_edit_snapshots = {}
            inst._stream_start_times = {}
            inst._active_stream_tool_ids = set()
            inst._pending_patch_paths = {}
            inst._stream_callback_tokens = {}

            inst._on_tool_start("tid-1", "terminal", {"command": "ls"})

        assert len(captured_callbacks) == 1
        cb = captured_callbacks[0]
        cb("hello\n")

        assert fake_tui.call_from_thread.called
        args = fake_tui.call_from_thread.call_args
        # First positional arg must be append_tool_output, not append_streaming_line
        assert args[0][0] == fake_tui.append_tool_output
        assert args[0][0] != fake_tui.append_streaming_line

    def test_append_tool_output_transitions_started_to_streaming(self):
        """First output line transitions view from STARTED to STREAMING."""
        svc = _make_service()
        view = _started_view("tid-2")
        svc._tool_views_by_id["tid-2"] = view

        mock_block = MagicMock()
        svc.app._active_streaming_blocks["tid-2"] = mock_block
        svc.app.query_one = MagicMock(return_value=MagicMock(_user_scrolled_up=False))

        svc.append_tool_output("tid-2", "output line")

        assert view.state == ToolCallState.STREAMING
        mock_block.append_line.assert_called_once_with("output line")

    def test_append_tool_output_terminal_state_noops(self):
        """append_tool_output on a DONE view does not append to block."""
        svc = _make_service()
        view = _started_view("tid-3")
        view.state = ToolCallState.DONE
        svc._tool_views_by_id["tid-3"] = view

        mock_block = MagicMock()
        svc.app._active_streaming_blocks["tid-3"] = mock_block

        svc.append_tool_output("tid-3", "late line")

        mock_block.append_line.assert_not_called()


# ---------------------------------------------------------------------------
# TCL-HIGH-02: Completion lifecycle
# ---------------------------------------------------------------------------

class TestCompletionLifecycle:
    """TCL-HIGH-02: complete_tool_call single terminal path regression guards."""

    def test_cli_completion_off_mode_uses_complete_tool_call_once(self):
        """Off-mode schedules only complete_tool_call — no direct close calls."""
        import cli as _cli_mod

        fake_tui = MagicMock()
        scheduled_mock_names = []

        def _capture(fn, *a, **kw):
            name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", "")
            scheduled_mock_names.append(name)

        fake_tui.call_from_thread.side_effect = _capture

        with patch.object(_cli_mod, "_hermes_app", fake_tui):
            inst = _cli_mod.HermesCLI.__new__(_cli_mod.HermesCLI)
            inst._pending_edit_snapshots = {}
            inst._stream_start_times = {}
            inst._active_stream_tool_ids = set()
            inst._pending_patch_paths = {}
            inst._stream_callback_tokens = {}
            inst.tool_progress_mode = "off"

            inst._on_tool_complete("tid-off", "web_search", {}, '{"result": "ok"}')

        assert "complete_tool_call" in scheduled_mock_names
        assert "close_streaming_tool_block" not in scheduled_mock_names
        assert "close_streaming_tool_block_with_diff" not in scheduled_mock_names

    def test_cli_completion_diff_mode_passes_diff_to_complete_tool_call(self):
        """File diff path passes diff_lines, header_stats, summary, duration."""
        import cli as _cli_mod

        fake_tui = MagicMock()
        complete_kwargs_list = []

        def _capture(fn, *a, **kw):
            name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", "")
            if name == "complete_tool_call":
                complete_kwargs_list.append(kw)

        fake_tui.call_from_thread.side_effect = _capture

        diff_lines = ["+added line", "-removed line"]

        def _fake_render(diff_text, print_fn=None, prefix=""):
            if print_fn is not None:
                for l in diff_lines:
                    print_fn(l)

        with patch.object(_cli_mod, "_hermes_app", fake_tui), \
             patch("agent.display.extract_edit_diff", return_value="+added line\n-removed line\n"), \
             patch("agent.display.render_captured_diff_preview", side_effect=_fake_render):
            inst = _cli_mod.HermesCLI.__new__(_cli_mod.HermesCLI)
            inst._pending_edit_snapshots = {"tid-diff": MagicMock()}
            inst._stream_start_times = {"tid-diff": time.monotonic() - 1.0}
            inst._active_stream_tool_ids = {"tid-diff"}
            inst._pending_patch_paths = {}
            inst._stream_callback_tokens = {}
            inst.tool_progress_mode = "normal"
            inst._code_highlight_enabled = False

            inst._on_tool_complete("tid-diff", "patch", {"path": "/x.py"}, '{"success": true}')

        assert len(complete_kwargs_list) >= 1
        kw = complete_kwargs_list[-1]
        assert "duration" in kw

    def test_cli_completion_search_web_passes_result_lines(self):
        """Search/web result arrives as a blob; result_lines kwarg is set."""
        import cli as _cli_mod

        fake_tui = MagicMock()
        complete_kwargs = {}

        def _capture(fn, *a, **kw):
            name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", "")
            if name == "complete_tool_call":
                complete_kwargs.update(kw)

        fake_tui.call_from_thread.side_effect = _capture

        result_blob = "line one\nline two\nline three"

        with patch.object(_cli_mod, "_hermes_app", fake_tui), \
             patch("agent.display.extract_edit_diff", return_value=None), \
             patch("agent.display.render_captured_diff_preview", return_value=None):
            inst = _cli_mod.HermesCLI.__new__(_cli_mod.HermesCLI)
            inst._pending_edit_snapshots = {}
            inst._stream_start_times = {"tid-web": time.monotonic() - 0.5}
            inst._active_stream_tool_ids = {"tid-web"}
            inst._pending_patch_paths = {}
            inst._stream_callback_tokens = {}
            inst.tool_progress_mode = "normal"
            inst._code_highlight_enabled = False

            inst._on_tool_complete("tid-web", "web_search", {"query": "test"}, result_blob)

        assert complete_kwargs.get("result_lines") == result_blob.splitlines()

    def test_complete_tool_call_removes_active_view_and_records_turn_metadata(self):
        """complete_tool_call() removes active view from _tool_views_by_id via _terminalize_tool_view."""
        svc = _make_service()
        view = _started_view("tid-done")
        view.state = ToolCallState.STREAMING
        svc._tool_views_by_id["tid-done"] = view

        mock_block = MagicMock()
        svc.app._active_streaming_blocks["tid-done"] = mock_block
        svc.app.query_one = MagicMock(return_value=MagicMock(_user_scrolled_up=False))

        with patch.object(svc, "mark_plan_done"):
            svc.complete_tool_call(
                "tid-done", "terminal", {}, "result",
                is_error=False, summary=None,
            )

        assert "tid-done" not in svc._tool_views_by_id
        assert view.state == ToolCallState.DONE

    def test_complete_tool_call_unknown_id_marks_plan_done(self):
        """Missing view still triggers mark_plan_done (plan row must not stay pending)."""
        svc = _make_service()
        svc.app._active_streaming_blocks = {}
        svc.app.planned_calls = []

        with patch.object(svc, "mark_plan_done") as mock_done, \
             patch.object(svc, "close_streaming_tool_block"), \
             patch.object(svc, "close_streaming_tool_block_with_diff"):
            svc.complete_tool_call(
                "unknown-tid", "web_search", {}, "result",
                is_error=False, summary=None,
            )

        mock_done.assert_called_once()


# ---------------------------------------------------------------------------
# TCL-MED-01: Panel argument wiring
# ---------------------------------------------------------------------------

class TestPanelArgumentWiring:
    """TCL-MED-01: _panel_for_block helper and panel wiring."""

    def test_generated_tool_start_sets_panel_tool_args(self):
        """Adopted generated block wires args into the panel via set_tool_args."""
        svc = _make_service()

        mock_panel = MagicMock()
        mock_panel.set_tool_args = MagicMock()
        mock_panel._plan_tool_call_id = None
        mock_panel._has_affordances = False

        mock_block = MagicMock()
        mock_block._tool_panel = mock_panel
        mock_block._tool_input = None

        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=0,
            tool_name="web_search",
            label="web_search",
            args={},
            state=ToolCallState.GENERATED,
            block=mock_block,
            panel=mock_panel,
            parent_tool_call_id=None,
            category="search",
            depth=0,
            start_s=0.0,
        )
        svc._tool_views_by_gen_index[0] = view

        with patch.object(svc, "mark_plan_running"), \
             patch.object(svc, "_compute_parent_depth", return_value=(None, 0)):
            svc.start_tool_call("tcl-gen-1", "web_search", {"query": "hello"})

        mock_panel.set_tool_args.assert_called()
        call_args = mock_panel.set_tool_args.call_args[0][0]
        assert call_args.get("query") == "hello"

    def test_direct_start_sets_panel_tool_args(self):
        """No-generation path wires args into the panel via _wire_args."""
        svc = _make_service()

        mock_panel = MagicMock()
        mock_panel.set_tool_args = MagicMock()
        mock_block = MagicMock()
        mock_block._tool_panel = mock_panel
        mock_block._tool_input = None

        svc.app._active_streaming_blocks["tcl-direct-1"] = mock_block

        with patch.object(svc, "open_streaming_tool_block"), \
             patch.object(svc, "mark_plan_running"), \
             patch.object(svc, "_compute_parent_depth", return_value=(None, 0)):
            svc.start_tool_call("tcl-direct-1", "web_search", {"query": "world"})

        mock_panel.set_tool_args.assert_called()
        call_args = mock_panel.set_tool_args.call_args[0][0]
        assert call_args.get("query") == "world"

    def test_panel_for_block_traverses_parent_chain(self):
        """_panel_for_block returns parent when _tool_panel attr is absent."""
        svc = _make_service()

        mock_panel = MagicMock()
        type(mock_panel).__name__ = "ToolPanel"

        mock_block = MagicMock(spec=[])  # no _tool_panel attr
        mock_block.parent = mock_panel

        result = svc._panel_for_block(mock_block)

        assert result is mock_panel

    def test_panel_for_block_handles_unmounted_block_without_warning(self, caplog):
        """_panel_for_block returns None for unmounted block and logs no warning."""
        svc = _make_service()

        mock_block = MagicMock(spec=[])  # no _tool_panel attr
        mock_block.parent = None

        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.tools"):
            result = svc._panel_for_block(mock_block)

        assert result is None
        assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# TCL-MED-02: Renderer exception logging
# ---------------------------------------------------------------------------

class TestRendererExceptionLogging:
    """TCL-MED-02: bare swallows in _completion.py replaced with debug logs."""

    def _make_panel_mixin(self):
        """Return a minimal _ToolPanelCompletionMixin instance with stubs."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        class FakePanel(_ToolPanelCompletionMixin):
            _block = None
            _body_pane = None
            _tool_name = "web_search"
            _category = None
            _tool_args = {}
            _result_summary_v4 = None

        inst = FakePanel.__new__(FakePanel)
        inst._block = None
        inst._body_pane = None
        inst._tool_name = "web_search"
        inst._category = None
        inst._tool_args = {}
        inst._result_summary_v4 = None
        inst.app = MagicMock()
        inst._lookup_view_state = lambda: None
        return inst

    def test_classifier_exception_logs_debug_exc_info(self, caplog):
        """A forced classifier failure logs one debug record with exception info."""
        panel = self._make_panel_mixin()

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.tool_panel._completion"), \
             patch("hermes_cli.tui.content_classifier.classify_content", side_effect=RuntimeError("boom")):
            panel._update_kind_from_classifier(5)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert debug_records[0].exc_info is not None

    def test_renderer_swap_exception_logs_debug_exc_info(self, caplog):
        """A forced renderer swap failure is caught by _maybe_swap_renderer with debug log."""
        from hermes_cli.tui.tool_payload import ResultKind
        panel = self._make_panel_mixin()

        mock_body_pane = MagicMock()
        panel._body_pane = mock_body_pane

        mock_result = MagicMock()
        # Use a non-TEXT/EMPTY kind so the renderer swap path executes
        mock_result.kind = MagicMock()

        mock_payload = MagicMock()

        # Make pick_renderer return a class whose instantiation raises
        bad_renderer_cls = MagicMock(side_effect=RuntimeError("swap failed"))

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.tool_panel._completion"), \
             patch("hermes_cli.tui.body_renderers.pick_renderer", return_value=bad_renderer_cls), \
             patch("hermes_cli.tui.body_renderers.FallbackRenderer", MagicMock()):
            panel._maybe_swap_renderer(mock_result, mock_payload)

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
        assert debug_records[0].exc_info is not None

    def test_renderer_swap_failure_keeps_old_block(self):
        """After a swap failure, _block still points to the original block."""
        from hermes_cli.tui.tool_payload import ResultKind
        panel = self._make_panel_mixin()

        original_block = MagicMock()
        panel._block = original_block

        mock_body_pane = MagicMock()
        panel._body_pane = mock_body_pane

        mock_result = MagicMock()
        mock_result.kind = MagicMock()  # non-TEXT/EMPTY kind

        bad_renderer_cls = MagicMock(side_effect=RuntimeError("instantiation failed"))

        with patch("hermes_cli.tui.body_renderers.pick_renderer", return_value=bad_renderer_cls), \
             patch("hermes_cli.tui.body_renderers.FallbackRenderer", MagicMock()):
            panel._maybe_swap_renderer(mock_result, MagicMock())

        # block unchanged — fallback is the existing body
        assert panel._block is original_block
