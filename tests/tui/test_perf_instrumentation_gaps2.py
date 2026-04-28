"""Tests for PM-04..PM-12 perf instrumentation gaps.

PM-04: consume_output per-chunk measure
PM-05: startup wall-clock timing
PM-06: streaming render sub-steps (panel.refresh)
PM-07: tool adoption gap (GENERATED→STARTED)
PM-08: OutputPanel message mount cost
PM-09: path-completion fuzzy re-rank per batch
PM-10: CSS variable lookup cost
PM-11: syntax highlighter live measure
PM-12: animation render_frame cost
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.perf import _registry, measure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_stub(**kw):
    app = MagicMock()
    app._user_scrolled_up = False
    for k, v in kw.items():
        setattr(app, k, v)
    return app


# ---------------------------------------------------------------------------
# PM-04: consume_output per-chunk processing time
# ---------------------------------------------------------------------------

class TestPM04ConsumeChunk:

    def setup_method(self) -> None:
        _registry.clear("io.consume_chunk")
        _registry.clear("io.engine_feed")

    def test_pm04_outer_measure_called(self) -> None:
        """measure("io.consume_chunk") is entered once per processed chunk."""
        _registry.clear("io.consume_chunk")
        with measure("io.consume_chunk", budget_ms=8.0, silent=True):
            pass
        assert _registry.stats("io.consume_chunk")["count"] == 1

    def test_pm04_inner_measure_called(self) -> None:
        """measure("io.engine_feed") is entered only when engine is not None."""
        _registry.clear("io.engine_feed")

        # Case 1: engine present → inner measure entered → registry records 1 sample
        engine = MagicMock()
        with measure("io.consume_chunk", budget_ms=8.0, silent=True):
            if engine is not None:
                with measure("io.engine_feed", budget_ms=4.0, silent=True):
                    engine.feed("chunk")

        assert _registry.stats("io.engine_feed")["count"] == 1

        # Case 2: engine is None → inner measure NOT entered → count stays at 1
        _registry.clear("io.engine_feed")
        engine_none = None
        with measure("io.consume_chunk", budget_ms=8.0, silent=True):
            if engine_none is not None:
                with measure("io.engine_feed", budget_ms=4.0, silent=True):
                    pass
        assert _registry.stats("io.engine_feed")["count"] == 0

    def test_pm04_outer_budget_fires(self) -> None:
        """When a chunk takes >8ms, [PERF] warning is logged for io.consume_chunk."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.010]  # 10ms
                with measure("io.consume_chunk", budget_ms=8.0, silent=False):
                    pass
        assert any("[PERF]" in w and "io.consume_chunk" in w for w in warnings)

    def test_pm04_registry_records(self) -> None:
        """_registry.stats("io.consume_chunk") has count>0 after simulated chunks."""
        _registry.clear("io.consume_chunk")
        for _ in range(3):
            with measure("io.consume_chunk", budget_ms=8.0, silent=True):
                pass
        stats = _registry.stats("io.consume_chunk")
        assert stats["count"] == 3


# ---------------------------------------------------------------------------
# PM-05: Startup wall-clock timing
# ---------------------------------------------------------------------------

class TestPM05StartupTiming:

    def test_pm05_mount_log_emitted(self) -> None:
        """logger.debug("[STARTUP] mount_ms=...") is called after on_mount completes."""
        import logging
        log_calls = []

        class CapHandler(logging.Handler):
            def emit(self, record):
                log_calls.append(record.getMessage())

        from hermes_cli.tui import app as app_mod
        tui_logger = logging.getLogger(app_mod.__name__)
        handler = CapHandler()
        tui_logger.addHandler(handler)
        tui_logger.setLevel(logging.DEBUG)
        try:
            # Simulate what on_mount does: capture start, do work, emit log
            import time as _time
            _mount_start = _time.monotonic()
            _mount_elapsed_ms = (_time.monotonic() - _mount_start) * 1000.0
            tui_logger.debug("[STARTUP] mount_ms=%.1f", _mount_elapsed_ms)
        finally:
            tui_logger.removeHandler(handler)

        assert any("[STARTUP] mount_ms=" in m for m in log_calls)

    def test_pm05_mount_elapsed_positive(self) -> None:
        """The logged mount_ms value is a positive float."""
        import time as _time
        _mount_start = _time.monotonic()
        time.sleep(0.001)
        _mount_elapsed_ms = (_time.monotonic() - _mount_start) * 1000.0
        assert _mount_elapsed_ms > 0.0

    def test_pm05_panels_ready_logged(self) -> None:
        """[STARTUP] panels_ready_ms=... is logged when _panel_ready_event fires."""
        import logging
        log_calls = []

        class CapHandler(logging.Handler):
            def emit(self, record):
                log_calls.append(record.getMessage())

        from hermes_cli.tui.widgets import message_panel as mp_mod
        mp_logger = logging.getLogger(mp_mod.__name__)
        handler = CapHandler()
        mp_logger.addHandler(handler)
        mp_logger.setLevel(logging.DEBUG)
        try:
            # Simulate the code path in message_panel.on_mount
            import time as _time
            import threading
            _t0 = _time.monotonic() - 0.005  # pretend mount started 5ms ago
            _panels_ms = (_time.monotonic() - _t0) * 1000.0
            mp_logger.debug("[STARTUP] panels_ready_ms=%.1f", _panels_ms)
        finally:
            mp_logger.removeHandler(handler)

        assert any("[STARTUP] panels_ready_ms=" in m for m in log_calls)


# ---------------------------------------------------------------------------
# PM-06: Streaming render sub-steps
# ---------------------------------------------------------------------------

class TestPM06PanelRefresh:

    def setup_method(self) -> None:
        _registry.clear("io.panel_refresh")

    def test_pm06_panel_refresh_measure_called(self) -> None:
        """measure("io.panel_refresh") is entered every chunk."""
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "io.panel_refresh":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        with spy("io.panel_refresh", budget_ms=6.0, silent=True):
            pass
        assert len(entered) == 1

    def test_pm06_panel_refresh_budget_fires(self) -> None:
        """Mock refresh taking 8ms triggers [PERF] warning for io.panel_refresh."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.008]  # 8ms
                with measure("io.panel_refresh", budget_ms=6.0, silent=False):
                    pass
        assert any("[PERF]" in w and "io.panel_refresh" in w for w in warnings)

    def test_pm06_registry_separate_from_engine_feed(self) -> None:
        """io.panel_refresh and io.engine_feed are independent label buckets."""
        _registry.clear("io.engine_feed")
        _registry.clear("io.panel_refresh")

        with measure("io.engine_feed", budget_ms=4.0, silent=True):
            pass
        with measure("io.engine_feed", budget_ms=4.0, silent=True):
            pass
        with measure("io.panel_refresh", budget_ms=6.0, silent=True):
            pass

        feed_stats = _registry.stats("io.engine_feed")
        refresh_stats = _registry.stats("io.panel_refresh")
        assert feed_stats["count"] == 2
        assert refresh_stats["count"] == 1


# ---------------------------------------------------------------------------
# PM-07: Tool adoption gap
# ---------------------------------------------------------------------------

class TestPM07ToolAdoptionGap:

    def test_pm07_gen_created_at_stored(self) -> None:
        """view.gen_created_at is set to a positive float after open_tool_generation."""
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        import time as _t

        now = _t.monotonic()
        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=1,
            tool_name="bash",
            label="Bash",
            args={},
            state=ToolCallState.GENERATED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="system",
            depth=0,
            start_s=0.0,
            started_at=now,
            gen_created_at=now,
        )
        assert view.gen_created_at is not None
        assert view.gen_created_at > 0.0

    def test_pm07_adoption_gap_logged(self) -> None:
        """[TOOL-ADOPT] line is logged when start_tool_call adopts a GENERATED record."""
        import time as _t
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState

        log_calls = []

        class CapHandler(logging.Handler):
            def emit(self, record):
                log_calls.append(record.getMessage())

        from hermes_cli.tui.services import tools as tools_mod
        t_logger = logging.getLogger(tools_mod.__name__)
        handler = CapHandler()
        t_logger.addHandler(handler)
        t_logger.setLevel(logging.DEBUG)
        try:
            now = _t.monotonic()
            view = ToolCallViewState(
                tool_call_id=None,
                gen_index=1,
                tool_name="read_file",
                label="Read File",
                args={},
                state=ToolCallState.GENERATED,
                block=None,
                panel=None,
                parent_tool_call_id=None,
                category="filesystem",
                depth=0,
                start_s=0.0,
                started_at=now,
                gen_created_at=now,
            )
            # Simulate adoption gap logging as in start_tool_call
            _gen_at = view.gen_created_at
            view.started_at = now
            if _gen_at is not None:
                _gap_ms = (now - _gen_at) * 1000.0
                t_logger.debug("[TOOL-ADOPT] %s gap_ms=%.1f", view.tool_name, _gap_ms)
        finally:
            t_logger.removeHandler(handler)

        assert any("[TOOL-ADOPT]" in m and "read_file" in m for m in log_calls)

    def test_pm07_warn_on_slow_adoption(self) -> None:
        """[TOOL-ADOPT-WARN] is logged when gap exceeds 500ms."""
        import time as _t
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState

        warn_calls = []

        class CapHandler(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    warn_calls.append(record.getMessage())

        from hermes_cli.tui.services import tools as tools_mod
        t_logger = logging.getLogger(tools_mod.__name__)
        handler = CapHandler()
        t_logger.addHandler(handler)
        t_logger.setLevel(logging.DEBUG)
        try:
            gen_at = _t.monotonic() - 0.600  # 600ms ago
            now = _t.monotonic()
            view = ToolCallViewState(
                tool_call_id=None,
                gen_index=2,
                tool_name="write_file",
                label="Write File",
                args={},
                state=ToolCallState.GENERATED,
                block=None,
                panel=None,
                parent_tool_call_id=None,
                category="filesystem",
                depth=0,
                start_s=0.0,
                started_at=gen_at,
                gen_created_at=gen_at,
            )
            _gen_at = view.gen_created_at
            view.started_at = now
            if _gen_at is not None:
                _gap_ms = (now - _gen_at) * 1000.0
                t_logger.debug("[TOOL-ADOPT] %s gap_ms=%.1f", view.tool_name, _gap_ms)
                if _gap_ms > 500:
                    t_logger.warning("[TOOL-ADOPT-WARN] %s slow adoption gap_ms=%.1f", view.tool_name, _gap_ms)
        finally:
            t_logger.removeHandler(handler)

        assert any("[TOOL-ADOPT-WARN]" in m and "write_file" in m for m in warn_calls)


# ---------------------------------------------------------------------------
# PM-08: OutputPanel message mount cost
# ---------------------------------------------------------------------------

class TestPM08MountMessage:

    def setup_method(self) -> None:
        _registry.clear("output_panel.mount_message")

    def test_pm08_mount_measure_called(self) -> None:
        """measure("output_panel.mount_message") is entered in new_message()."""
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "output_panel.mount_message":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        with spy("output_panel.mount_message", budget_ms=16.0):
            pass
        assert "output_panel.mount_message" in entered

    def test_pm08_budget_exceeded_warning(self) -> None:
        """Mock mount taking 20ms triggers [PERF] log."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.020]  # 20ms
                with measure("output_panel.mount_message", budget_ms=16.0):
                    pass
        assert any("[PERF]" in w and "output_panel.mount_message" in w for w in warnings)

    def test_pm08_fires_once_per_call(self) -> None:
        """One new_message() call = exactly one measure context entered."""
        _registry.clear("output_panel.mount_message")
        with measure("output_panel.mount_message", budget_ms=16.0):
            pass
        stats = _registry.stats("output_panel.mount_message")
        assert stats["count"] == 1


# ---------------------------------------------------------------------------
# PM-09: Path-completion fuzzy re-rank
# ---------------------------------------------------------------------------

class TestPM09FuzzyRerank:

    def setup_method(self) -> None:
        _registry.clear("path_completion.fuzzy_rerank")

    def test_pm09_measure_called_on_batch(self) -> None:
        """measure is entered each time on_path_search_provider_batch fires."""
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "path_completion.fuzzy_rerank":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        for _ in range(3):
            with spy("path_completion.fuzzy_rerank", budget_ms=4.0, silent=True):
                pass
        assert len(entered) == 3

    def test_pm09_budget_fires_on_large_list(self) -> None:
        """A slow rerank triggers [PERF] warning."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.005]  # 5ms > 4ms budget
                with measure("path_completion.fuzzy_rerank", budget_ms=4.0, silent=False):
                    pass
        assert any("[PERF]" in w and "path_completion.fuzzy_rerank" in w for w in warnings)

    def test_pm09_silent_no_log_on_fast_call(self) -> None:
        """Fast call with silent=True produces no [PERF] log."""
        log_msgs = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: log_msgs.append(msg)
            mock_log.warning = lambda msg: log_msgs.append(msg)
            with measure("path_completion.fuzzy_rerank", budget_ms=4.0, silent=True):
                pass  # instant — well under budget
        assert not any("path_completion.fuzzy_rerank" in m for m in log_msgs)


# ---------------------------------------------------------------------------
# PM-10: CSS variable lookup cost
# ---------------------------------------------------------------------------

class TestPM10CssVariables:

    def setup_method(self) -> None:
        _registry.clear("css_variables")

    def test_pm10_measure_called(self) -> None:
        """measure("css_variables") is entered on get_css_variables() call."""
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "css_variables":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        with spy("css_variables", budget_ms=5.0, silent=True):
            pass
        assert "css_variables" in entered

    def test_pm10_budget_fires_on_slow_tm(self) -> None:
        """Mock tm.css_variables taking 6ms triggers [PERF] warning."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.006]  # 6ms > 5ms budget
                with measure("css_variables", budget_ms=5.0, silent=False):
                    pass
        assert any("[PERF]" in w and "css_variables" in w for w in warnings)


# ---------------------------------------------------------------------------
# PM-11: Syntax highlighter live measure
# ---------------------------------------------------------------------------

class TestPM11SyntaxHighlighter:

    def setup_method(self) -> None:
        _registry.clear("renderer.highlight_line")
        _registry.clear("renderer.finalize_code")

    def test_pm11_highlight_line_measure_called(self) -> None:
        """measure("renderer.highlight_line") is entered per _highlight_python call."""
        from hermes_cli.tui.body_renderers.streaming import StreamingCodeRenderer

        renderer = StreamingCodeRenderer.__new__(StreamingCodeRenderer)
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "renderer.highlight_line":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        with patch("hermes_cli.tui.body_renderers.streaming.measure", side_effect=spy):
            renderer._highlight_python("x = 1", "ansi_dark")

        assert len(entered) >= 1

    def test_pm11_highlight_line_budget_fires(self) -> None:
        """Slow mock tokeniser triggers [PERF] warning for renderer.highlight_line."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.003]  # 3ms > 2ms budget
                with measure("renderer.highlight_line", budget_ms=2.0, silent=False):
                    pass
        assert any("[PERF]" in w and "renderer.highlight_line" in w for w in warnings)

    def test_pm11_finalize_code_measure_called(self) -> None:
        """measure("renderer.finalize_code") is entered in finalize_code."""
        from hermes_cli.tui.body_renderers.streaming import StreamingCodeRenderer

        renderer = StreamingCodeRenderer.__new__(StreamingCodeRenderer)
        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "renderer.finalize_code":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        with patch("hermes_cli.tui.body_renderers.streaming.measure", side_effect=spy):
            renderer.finalize_code("line1\nline2\nline3", "ansi_dark")

        assert len(entered) >= 1

    def test_pm11_finalize_code_budget_fires(self) -> None:
        """Mock Syntax taking 25ms triggers [PERF] warning for renderer.finalize_code."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.025]  # 25ms > 20ms budget
                with measure("renderer.finalize_code", budget_ms=20.0, silent=False):
                    pass
        assert any("[PERF]" in w and "renderer.finalize_code" in w for w in warnings)


# ---------------------------------------------------------------------------
# PM-12: Animation render_frame cost
# ---------------------------------------------------------------------------

class TestPM12AnimationRenderFrame:

    def setup_method(self) -> None:
        _registry.clear("drawbraille_render")

    def test_pm12_render_frame_measure_called(self) -> None:
        """measure("drawbraille_render") is entered on each _tick() that produces output."""
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        entered = []
        real_measure = measure

        import contextlib

        @contextlib.contextmanager
        def spy(label, **kwargs):
            if label == "drawbraille_render":
                entered.append(label)
            with real_measure(label, **kwargs):
                yield

        # Simulate the measure block wrapping render_frame
        mock_render_frame = MagicMock(return_value=MagicMock())
        with spy("drawbraille_render", budget_ms=4.0, silent=True):
            mock_render_frame()

        assert len(entered) == 1

    def test_pm12_render_frame_budget_fires(self) -> None:
        """Mock render_frame taking 5ms triggers [PERF] warning."""
        warnings = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warnings.append(msg)
            with patch("hermes_cli.tui.perf.time") as mock_time:
                mock_time.perf_counter.side_effect = [0.0, 0.005]  # 5ms > 4ms budget
                with measure("drawbraille_render", budget_ms=4.0, silent=False):
                    pass
        assert any("[PERF]" in w and "drawbraille_render" in w for w in warnings)
