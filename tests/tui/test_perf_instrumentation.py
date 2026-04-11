"""Tests for hermes_cli/tui/perf.py — measure(), WorkerWatcher, EventLoopLatencyProbe."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.perf import (
    EventLoopLatencyProbe,
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
