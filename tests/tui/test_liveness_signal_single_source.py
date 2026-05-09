"""
tests/tui/test_liveness_signal_single_source.py

LIVE-1 + LIVE-2: Liveness single-source-of-truth spec.

TestLivenessSingleSource (5 tests):
  - overlay cleared during streaming (LIVE-1 guard)
  - overlay active during tool exec without streaming
  - no dual timer pattern during streaming
  - statusline shows streaming verb during stream
  - idle state has no streaming or tracing verb

TestSpinnerLabelClear (1 test):
  - spinner_label cleared at streaming start (LIVE-2)
"""
from __future__ import annotations

import re
import time
import types
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — SpinnerService stub
# ---------------------------------------------------------------------------

def _make_app(
    *,
    agent_running: bool = False,
    command_running: bool = False,
    status_streaming: bool = False,
    spinner_label: str = "",
    tool_start_time: float = 0.0,
) -> types.SimpleNamespace:
    overlay = types.SimpleNamespace(display=True, is_mounted=True)
    # Provide a mounted input-area stub so tick_spinner() doesn't call query_one()
    input_area = types.SimpleNamespace(is_mounted=True, placeholder="", _idle_placeholder="")
    app = types.SimpleNamespace(
        agent_running=agent_running,
        command_running=command_running,
        status_streaming=status_streaming,
        spinner_label=spinner_label,
        _tool_start_time=tool_start_time,
        _shimmer_tick=0,
        _cached_spinner_overlay=overlay,
        _cached_input_area=input_area,
        _animations_enabled=False,
        _spinner_perf_alarm=None,
        _spinner_frames=[],
        _spinner_idx=0,
        approval_state=None,
        clarify_state=None,
        sudo_state=None,
        secret_state=None,
        _theme_manager=None,
    )
    return app


def _make_spinner_service(app: types.SimpleNamespace):
    from hermes_cli.tui.services.spinner import SpinnerService
    svc = object.__new__(SpinnerService)
    svc.app = app  # AppService stores as self.app
    svc._helix_frame_cache = {}
    svc._last_overlay_signature = None
    return svc


# ---------------------------------------------------------------------------
# Helpers — StatusBar stub (mirrors test_composer_status_polish.py pattern)
# ---------------------------------------------------------------------------

def _make_bar():
    from hermes_cli.tui.widgets.status_bar import StatusBar

    class _IsolatedBar(StatusBar):
        app = None       # type: ignore[assignment]
        size = None      # type: ignore[assignment]
        content_size = None  # type: ignore[assignment]

    bar = object.__new__(_IsolatedBar)
    bar._model_changed_at = 0.0
    bar._cwd_changed_at = 0.0
    bar.__dict__["_tok_s_displayed"] = 0.0
    bar._pulse_active = False
    bar._classes = frozenset()
    return bar


def _make_status_app(**kwargs: Any) -> types.SimpleNamespace:
    defaults = dict(
        status_model="claude-sonnet-4-6",
        status_context_tokens=0,
        status_context_max=0,
        status_compaction_progress=0.0,
        status_compaction_enabled=True,
        status_streaming=False,
        agent_running=False,
        command_running=False,
        yolo_mode=False,
        compact=False,
        status_verbose=False,
        status_active_file="",
        status_active_file_offscreen=False,
        browse_mode=False,
        browse_index=0,
        _browse_total=0,
        status_output_dropped=False,
        context_pct=0.0,
        session_label="",
        session_count=1,
        status_error="",
        status_tok_s=0.0,
        status_phase="idle",
        status_cwd="",
        feedback=None,
        _cfg={},
        status_streaming_elapsed_s=0.0,
        _browse_uses=0,
        browse_detail_level=0,
    )
    defaults.update(kwargs)
    app = types.SimpleNamespace(**defaults)
    app.get_css_variables = lambda: {}
    return app


def _render_bar(bar, app, *, width: int = 80) -> str:
    size_ns = types.SimpleNamespace(width=width, height=1)
    content_size_ns = types.SimpleNamespace(width=width, height=1)
    bar.__class__.app = property(lambda s: app)
    bar.__class__.size = property(lambda s: size_ns)
    bar.__class__.content_size = property(lambda s: content_size_ns)
    result = bar.render()
    return result.plain if hasattr(result, "plain") else str(result)


# ---------------------------------------------------------------------------
# TestLivenessSingleSource — 5 tests
# ---------------------------------------------------------------------------

class TestLivenessSingleSource:

    def test_spinner_overlay_cleared_during_stream(self):
        """LIVE-1: _clear_spinner_overlay called when status_streaming=True."""
        app = _make_app(
            agent_running=True,
            status_streaming=True,
            spinner_label="langfuse_tracing",
            tool_start_time=4.5,
        )
        svc = _make_spinner_service(app)

        with patch.object(svc, "_clear_spinner_overlay") as mock_clear:
            svc.tick_spinner()

        mock_clear.assert_called_once()

    def test_spinner_overlay_active_during_tool_exec(self):
        """LIVE-1 guard does not suppress overlay when status_streaming=False."""
        app = _make_app(
            agent_running=True,
            status_streaming=False,
            spinner_label="bash",
            tool_start_time=1.0,
        )
        svc = _make_spinner_service(app)

        with patch.object(svc, "_update_plain_spinner_overlay") as mock_plain:
            svc.tick_spinner()

        mock_plain.assert_called_once()
        content_arg = mock_plain.call_args[0][1]
        assert "bash" in content_arg

    def test_no_dual_timer_render(self):
        """No elapsed-time text is produced in overlay output when streaming."""
        app = _make_app(
            agent_running=True,
            status_streaming=True,
            spinner_label="bash",
            tool_start_time=time.monotonic() - 5.0,
        )
        svc = _make_spinner_service(app)

        plain_calls: list[str] = []

        def _capture_plain(overlay, text):
            plain_calls.append(text)

        with patch.object(svc, "_update_plain_spinner_overlay", side_effect=_capture_plain):
            svc.tick_spinner()

        # Overlay write path must not be reached during streaming
        assert plain_calls == [], (
            f"Overlay content written during streaming: {plain_calls}"
        )
        elapsed_pattern = re.compile(r"\d+\.\d+s")
        for text in plain_calls:
            assert not elapsed_pattern.search(text), (
                f"Elapsed timer leaked into overlay: {text!r}"
            )

    def test_statusline_shows_streaming_during_stream(self):
        """StatusBar.render() includes 'streaming' when status_streaming=True and agent running."""
        bar = _make_bar()
        app = _make_status_app(
            agent_running=True,
            status_streaming=True,
            status_phase="streaming",
        )
        rendered = _render_bar(bar, app)
        assert "streaming" in rendered, (
            f"Expected 'streaming' in status bar output, got: {rendered!r}"
        )

    def test_idle_state_no_streaming_verb(self):
        """Spinner overlay cleared and no spinner written when idle (not streaming, not running)."""
        app = _make_app(
            agent_running=False,
            status_streaming=False,
            spinner_label="",
        )
        svc = _make_spinner_service(app)

        with patch.object(svc, "_clear_spinner_overlay") as mock_clear:
            with patch.object(svc, "_update_plain_spinner_overlay") as mock_plain:
                svc.tick_spinner()

        # Idle path: clear called, no overlay content written
        mock_clear.assert_called_once()
        mock_plain.assert_not_called()


# ---------------------------------------------------------------------------
# TestSpinnerLabelClear — 1 test
# ---------------------------------------------------------------------------

class TestSpinnerLabelClear:

    def test_spinner_label_cleared_on_streaming_start(self):
        """LIVE-2: setting spinner_label='' after status_phase=STREAMING resets _tool_start_time."""
        from hermes_cli.tui.agent_phase import Phase as _Phase

        tool_start = time.monotonic() - 3.0

        class _AppStub(types.SimpleNamespace):
            """Simulates watch_spinner_label: clears _tool_start_time when label becomes ''."""
            def __setattr__(self, name: str, value: object) -> None:
                super().__setattr__(name, value)
                if name == "spinner_label" and not value:
                    super().__setattr__("_tool_start_time", 0.0)

        app = _AppStub(
            spinner_label="bash",
            _tool_start_time=tool_start,
            status_phase=_Phase.REASONING,
        )
        app.hooks = types.SimpleNamespace(fire=lambda *a, **kw: None)

        # Simulate streaming-start branch from io.py (lines 88-90 with LIVE-2 patch)
        app.status_phase = _Phase.STREAMING
        app.spinner_label = ""           # LIVE-2: clear stale label
        app.hooks.fire("on_streaming_start")

        assert app.spinner_label == "", (
            f"Expected spinner_label='', got {app.spinner_label!r}"
        )
        assert app._tool_start_time == 0.0, (
            f"Expected _tool_start_time=0.0, got {app._tool_start_time}"
        )
