"""Tests for hermes_cli/tui/perf.py — measure(), WorkerWatcher, EventLoopLatencyProbe."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.perf import (
    EventLoopLatencyProbe,
    FrameRateProbe,
    PerfResult,
    WorkerWatcher,
    measure,
)


# ---------------------------------------------------------------------------
# measure() context manager
# ---------------------------------------------------------------------------

class TestMeasure:
    def test_yields_perf_result(self) -> None:
        with measure("test", budget_ms=100.0, silent=True) as r:
            assert isinstance(r, PerfResult)
            assert r.label == "test"

    def test_elapsed_ms_populated_after_block(self) -> None:
        with measure("test", budget_ms=100.0, silent=True) as r:
            pass  # near-instant
        assert r.elapsed_ms >= 0.0
        assert r.elapsed_ms < 100.0  # sanity

    def test_over_budget_flag(self) -> None:
        with measure("slow", budget_ms=0.0001, silent=True) as r:
            time.sleep(0.001)  # guaranteed over budget
        assert r.over_budget is True
        assert r.elapsed_ms > 0.0

    def test_under_budget_flag(self) -> None:
        with measure("fast", budget_ms=1000.0, silent=True) as r:
            pass
        assert r.over_budget is False

    def test_elapsed_includes_block_time(self) -> None:
        target_s = 0.01
        with measure("timed", budget_ms=1000.0, silent=True) as r:
            time.sleep(target_s)
        # Allow ±50 % tolerance for CI scheduler jitter
        assert r.elapsed_ms >= target_s * 1000 * 0.5

    def test_silent_suppresses_log(self) -> None:
        with patch("hermes_cli.tui.perf.log") as mock_log:
            with measure("test", budget_ms=100.0, silent=True):
                pass
        mock_log.assert_not_called()
        mock_log.warning.assert_not_called()

    def test_over_budget_logs_warning(self) -> None:
        with patch("hermes_cli.tui.perf.log") as mock_log:
            with measure("test", budget_ms=0.0, silent=False):
                pass
        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0]
        assert "OVER" in warning_msg
        assert "test" in warning_msg

    def test_exception_propagates_and_elapsed_set(self) -> None:
        r: PerfResult | None = None
        with pytest.raises(ValueError):
            with measure("err", budget_ms=100.0, silent=True) as r:
                raise ValueError("boom")
        assert r is not None
        assert r.elapsed_ms >= 0.0


# ---------------------------------------------------------------------------
# WorkerWatcher
# ---------------------------------------------------------------------------

class TestWorkerWatcher:
    def _app_with_workers(self, count: int) -> MagicMock:
        app = MagicMock()
        app.workers = list(range(count))  # fake worker list
        return app

    def test_returns_worker_count(self) -> None:
        app = self._app_with_workers(3)
        ww = WorkerWatcher(app, warn_threshold=10)
        assert ww.tick() == 3

    def test_peak_updated(self) -> None:
        app = self._app_with_workers(0)
        ww = WorkerWatcher(app)
        app.workers = list(range(5))
        ww.tick()
        assert ww.peak == 5
        app.workers = list(range(2))
        ww.tick()
        assert ww.peak == 5  # peak never decreases

    def test_warning_on_threshold_exceeded(self) -> None:
        app = self._app_with_workers(10)
        ww = WorkerWatcher(app, warn_threshold=5)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            ww.tick()
        mock_log.warning.assert_called_once()
        warning_msg = mock_log.warning.call_args[0][0]
        assert "leak" in warning_msg.lower() or "possible" in warning_msg.lower()

    def test_no_warning_under_threshold(self) -> None:
        app = self._app_with_workers(2)
        ww = WorkerWatcher(app, warn_threshold=8)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            ww.tick()
        mock_log.warning.assert_not_called()

    def test_heartbeat_every_60_ticks(self) -> None:
        app = self._app_with_workers(1)
        ww = WorkerWatcher(app)
        log_calls = []
        with patch("hermes_cli.tui.perf.log", side_effect=lambda msg: log_calls.append(msg)):
            for _ in range(60):
                ww.tick()
        heartbeats = [m for m in log_calls if "heartbeat" in m]
        assert len(heartbeats) == 1


# ---------------------------------------------------------------------------
# EventLoopLatencyProbe
# ---------------------------------------------------------------------------

class TestEventLoopLatencyProbe:
    def test_first_tick_returns_zero(self) -> None:
        probe = EventLoopLatencyProbe()
        assert probe.tick() == 0.0

    def test_second_tick_returns_positive(self) -> None:
        probe = EventLoopLatencyProbe()
        probe.tick()
        time.sleep(0.01)
        actual_ms = probe.tick()
        assert actual_ms > 0.0

    def test_over_budget_count_increments(self) -> None:
        probe = EventLoopLatencyProbe(budget_ms=0.0)
        probe.tick()
        time.sleep(0.001)
        probe.tick()  # any jitter will exceed 0 ms budget
        assert probe.over_budget_count >= 1

    def test_no_over_budget_on_healthy_interval(self) -> None:
        probe = EventLoopLatencyProbe(budget_ms=5000.0, expected_interval_s=0.001)
        probe.tick()
        time.sleep(0.001)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            probe.tick()
        mock_log.warning.assert_not_called()
        assert probe.over_budget_count == 0

    def test_over_budget_logs_warning(self) -> None:
        probe = EventLoopLatencyProbe(budget_ms=0.0)
        probe.tick()
        time.sleep(0.001)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            probe.tick()
        mock_log.warning.assert_called_once()
        msg = mock_log.warning.call_args[0][0]
        assert "[LOOP]" in msg


# ---------------------------------------------------------------------------
# FrameRateProbe
# ---------------------------------------------------------------------------

class TestFrameRateProbe:
    def test_first_tick_returns_zeros(self) -> None:
        probe = FrameRateProbe()
        fps, avg_ms = probe.tick()
        assert fps == 0.0
        assert avg_ms == 0.0

    def test_second_tick_returns_nonzero(self) -> None:
        probe = FrameRateProbe()
        probe.tick()
        time.sleep(0.05)
        fps, avg_ms = probe.tick()
        assert fps > 0.0
        assert avg_ms > 0.0

    def test_fps_approximates_interval(self) -> None:
        """~10 Hz ticks should yield ~10 fps."""
        probe = FrameRateProbe(window=5)
        for _ in range(6):
            probe.tick()
            time.sleep(0.1)
        # Allow generous tolerance for CI scheduler jitter
        assert 3.0 < probe.fps < 30.0

    def test_avg_ms_approximates_interval(self) -> None:
        probe = FrameRateProbe(window=4)
        for _ in range(5):
            probe.tick()
            time.sleep(0.05)
        # Should be ~50ms ± large CI tolerance
        assert 5.0 < probe.avg_ms < 500.0

    def test_properties_match_tick_return(self) -> None:
        probe = FrameRateProbe()
        probe.tick()
        time.sleep(0.01)
        fps, avg_ms = probe.tick()
        assert fps == probe.fps
        assert avg_ms == probe.avg_ms

    def test_rolling_window_trims_old_samples(self) -> None:
        probe = FrameRateProbe(window=3)
        for _ in range(10):
            probe.tick()
            time.sleep(0.01)
        assert len(probe._samples) <= 3

    def test_logs_at_log_every_interval(self) -> None:
        probe = FrameRateProbe(window=5, log_every=3)
        probe.tick()
        time.sleep(0.01)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            # tick 2 and 3 — tick 3 is the log_every=3 boundary
            probe.tick()
            probe.tick()
        mock_log.assert_called_once()
        msg = mock_log.call_args[0][0]
        assert "[FPS]" in msg
        assert "fps=" in msg
        assert "avg_ms=" in msg

    def test_no_log_before_log_every(self) -> None:
        probe = FrameRateProbe(window=5, log_every=100)
        probe.tick()
        time.sleep(0.01)
        with patch("hermes_cli.tui.perf.log") as mock_log:
            probe.tick()
        mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# FPSCounter widget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fps_counter_default_hidden() -> None:
    """FPSCounter starts with display:none (no --visible class)."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.widgets import FPSCounter
        counter = app.query_one(FPSCounter)
        assert not counter.has_class("--visible")


@pytest.mark.asyncio
async def test_fps_counter_toggle_keybind() -> None:
    """Ctrl+\\ shows FPSCounter; second press hides it."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import FPSCounter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        counter = app.query_one(FPSCounter)
        assert not counter.has_class("--visible")

        await pilot.press("f8")
        await pilot.pause()
        assert counter.has_class("--visible")
        assert app.fps_hud_visible is True

        await pilot.press("f8")
        await pilot.pause()
        assert not counter.has_class("--visible")
        assert app.fps_hud_visible is False


@pytest.mark.asyncio
async def test_fps_counter_reactive_update() -> None:
    """Setting fps_hud_visible pushes fps/avg_ms into FPSCounter."""
    from unittest.mock import MagicMock
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.widgets import FPSCounter

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.fps_hud_visible = True
        await pilot.pause()
        counter = app.query_one(FPSCounter)
        counter.fps = 9.5
        counter.avg_ms = 105.2
        await pilot.pause()
        assert counter.fps == pytest.approx(9.5)
        assert counter.avg_ms == pytest.approx(105.2)
