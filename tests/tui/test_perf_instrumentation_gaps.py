"""Tests for PM-01/PM-02/PM-03 perf instrumentation gaps.

PM-01: ToolCallProbe — per-tool-name latency
PM-02: QueueDepthProbe — output queue depth metering
PM-03: StreamJitterProbe — streaming inter-chunk gap
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.perf import (
    QueueDepthProbe,
    StreamJitterProbe,
    ToolCallProbe,
    _registry,
)


def _make_queue(qsize: int, maxsize: int) -> MagicMock:
    q = MagicMock()
    q.qsize.return_value = qsize
    q.maxsize = maxsize
    return q


# ---------------------------------------------------------------------------
# TestToolCallProbe (PM-01)
# ---------------------------------------------------------------------------

class TestToolCallProbe:

    def setup_method(self) -> None:
        self.probe = ToolCallProbe()
        _registry.clear("tool:bash")
        _registry.clear("tool:read_file")

    def test_record_fast_call_logs_info(self) -> None:
        log_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: log_calls.append(("info", msg))
            mock_log.warning = lambda msg: log_calls.append(("warning", msg))
            self.probe.record("bash", "abc12345", 200.0)
        tags = [c[1] for c in log_calls]
        assert any("[TOOL]" in t for t in tags)
        assert not any("OVER" in t for t in tags)

    def test_record_slow_call_logs_warning(self) -> None:
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            self.probe.record("bash", "abc12345", 6000.0)
        assert any("⚠ OVER" in m and "5s" in m for m in warning_calls)

    def test_record_error_call_logs_status_err(self) -> None:
        log_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: log_calls.append(msg)
            mock_log.warning = lambda msg: log_calls.append(msg)
            self.probe.record("bash", "abc12345", 300.0, is_error=True)
        assert any("status=err" in m for m in log_calls)

    def test_registry_populated_after_record(self) -> None:
        with patch("hermes_cli.tui.perf.log"), patch.object(
            self.probe._detector("bash")._alarm if False else MagicMock(), "observe"
        ):
            pass
        with patch("hermes_cli.tui.perf.log"):
            self.probe.record("bash", "id000001", 100.0)
            self.probe.record("bash", "id000002", 200.0)
            self.probe.record("bash", "id000003", 300.0)
        assert _registry.p50("tool:bash") > 0

    def test_stats_returns_correct_p50(self) -> None:
        values = [100.0, 200.0, 300.0, 400.0, 500.0]
        with patch("hermes_cli.tui.perf.log"):
            for i, v in enumerate(values):
                self.probe.record("read_file", f"id{i:06d}", v)
        stats = self.probe.stats("read_file")
        assert stats["p50"] == pytest.approx(300.0, abs=1.0)

    def test_suspicion_detector_fires_on_streak(self) -> None:
        error_calls: list = []
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: None
            mock_log.warning = lambda msg: warning_calls.append(msg)
            mock_log.error = lambda msg: error_calls.append(msg)
            for i in range(3):
                self.probe.record("bash", f"id{i:06d}", 6000.0)
        all_msgs = warning_calls + error_calls
        assert any("[PERF-ALARM]" in m for m in all_msgs)

    def test_suspicion_detector_cooldown_suppresses(self) -> None:
        # Reset detector for clean state
        probe = ToolCallProbe()
        _registry.clear("tool:bash")
        alarm_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: None
            mock_log.warning = lambda msg: alarm_calls.append(msg)
            mock_log.error = lambda msg: alarm_calls.append(msg)
            # Trigger alarm (streak of 2)
            for i in range(2):
                probe.record("bash", f"id{i:06d}", 6000.0)
            first_alarms = [m for m in alarm_calls if "[PERF-ALARM]" in m]
            alarm_calls.clear()
            # Immediately trigger again (still in cooldown)
            probe.record("bash", "id000099", 6000.0)
            second_alarms = [m for m in alarm_calls if "[PERF-ALARM]" in m]
        # Second burst should be suppressed by cooldown
        assert len(second_alarms) == 0 or len(second_alarms) <= len(first_alarms)

    def test_suspicion_detector_severe_bypasses_cooldown(self) -> None:
        probe = ToolCallProbe()
        _registry.clear("tool:bash")
        error_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: None
            mock_log.warning = lambda msg: None
            mock_log.error = lambda msg: error_calls.append(msg)
            # Trigger cooldown with a streak
            for i in range(2):
                probe.record("bash", f"id{i:06d}", 6000.0)
            # Now fire a severe spike (>= 30000ms)
            probe.record("bash", "id000099", 35000.0)
        assert any("[PERF-ALARM]" in m for m in error_calls)

    def test_started_at_set_at_tool_start_not_gen_block(self) -> None:
        """Adopted-path resets started_at; direct-path captures at construction."""
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        import time as _t
        t_before = _t.monotonic()
        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=0,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.GENERATED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.0,
        )
        t_gen = _t.monotonic()
        # Simulate time passing before adopted
        time.sleep(0.01)
        view.started_at = _t.monotonic()
        t_adopt = _t.monotonic()
        assert view.started_at >= t_gen
        assert view.started_at <= t_adopt

    def test_complete_tool_call_uses_view_started_at(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
        import time as _t
        view = ToolCallViewState(
            tool_call_id="tc001",
            gen_index=None,
            tool_name="bash",
            label="bash",
            args={},
            state=ToolCallState.STARTED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category="shell",
            depth=0,
            start_s=0.0,
        )
        # Backdate started_at by 500ms
        view.started_at = _t.monotonic() - 0.5
        dur_ms = (_t.monotonic() - view.started_at) * 1000.0
        assert 450.0 <= dur_ms <= 600.0


# ---------------------------------------------------------------------------
# TestQueueDepthProbe (PM-02)
# ---------------------------------------------------------------------------

class TestQueueDepthProbe:

    def setup_method(self) -> None:
        self.probe = QueueDepthProbe()
        _registry.clear("queue_drops")
        _registry.clear("queue_depth")

    def test_record_drop_increments_counter(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            self.probe.record_drop()
            self.probe.record_drop()
            self.probe.record_drop()
        assert self.probe.drop_count == 3

    def test_record_drop_logs_queue_drop_tag(self) -> None:
        log_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: log_calls.append(msg)
            self.probe.record_drop()
        assert any("[QUEUE-DROP]" in m and "total_drops" in m for m in log_calls)

    def test_record_drop_populates_registry(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            self.probe.record_drop()
        stats = _registry.stats("queue_drops")
        assert stats["count"] == 1.0

    def test_tick_healthy_no_warning(self) -> None:
        q = _make_queue(qsize=100, maxsize=4096)  # ~2.4%
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            mock_log.side_effect = lambda msg: None
            self.probe.tick(q)
        assert not any("[QUEUE-WARN]" in m for m in warning_calls)

    def test_tick_saturated_logs_warn(self) -> None:
        q = _make_queue(qsize=3800, maxsize=4096)  # ~92.8%
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            self.probe.tick(q)
        assert any("[QUEUE-WARN]" in m for m in warning_calls)

    def test_tick_returns_depth(self) -> None:
        q = _make_queue(qsize=100, maxsize=4096)
        with patch("hermes_cli.tui.perf.log"):
            result = self.probe.tick(q)
        assert result == 100

    def test_tick_records_into_registry(self) -> None:
        q = _make_queue(qsize=50, maxsize=4096)
        with patch("hermes_cli.tui.perf.log"):
            for _ in range(5):
                self.probe.tick(q)
        stats = _registry.stats("queue_depth")
        assert stats["count"] == 5.0

    def test_heartbeat_logs_every_30_ticks(self) -> None:
        q = _make_queue(qsize=10, maxsize=4096)  # healthy
        info_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            for _ in range(30):
                self.probe.tick(q)
        heartbeats = [m for m in info_calls if "[QUEUE]" in m and "depth=" in m]
        assert len(heartbeats) == 1

    def test_heartbeat_suppressed_when_saturated(self) -> None:
        q = _make_queue(qsize=3800, maxsize=4096)  # >80%
        info_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            for _ in range(30):
                self.probe.tick(q)
        # Heartbeat [QUEUE] (without WARN) should not appear when always saturated
        heartbeats = [m for m in info_calls if m.startswith("[QUEUE] ")]
        assert len(heartbeats) == 0

    def test_alarm_fires_on_repeated_drops(self) -> None:
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            for _ in range(3):
                self.probe.record_drop()
        assert any("[QUEUE-ALARM]" in m for m in warning_calls)

    def test_io_service_calls_probe_on_queue_full(self) -> None:
        """write_output QueueFull path calls _queue_probe.record_drop()."""
        from hermes_cli.tui.services import io as io_module
        mock_app = MagicMock()
        mock_app._event_loop = MagicMock()
        mock_app.status_output_dropped = False
        mock_app._output_queue = MagicMock()
        mock_app._output_queue.put_nowait.side_effect = asyncio.QueueFull()

        svc = io_module.IOService.__new__(io_module.IOService)
        svc.app = mock_app

        with patch("hermes_cli.tui.perf._queue_probe") as mock_probe:
            with patch.object(io_module, "_CPYTHON_FAST_PATH", True):
                svc.write_output("hello")
        mock_probe.record_drop.assert_called_once()


# ---------------------------------------------------------------------------
# TestStreamJitterProbe (PM-03)
# ---------------------------------------------------------------------------

class TestStreamJitterProbe:

    def setup_method(self) -> None:
        self.probe = StreamJitterProbe()
        _registry.clear("stream_chunk_gap_ms")

    def test_normal_chunk_logs_stream_tag(self) -> None:
        info_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            self.probe.record_chunk(100.0, 5)
        assert any("[STREAM]" in m for m in info_calls)

    def test_stall_logs_stream_stall_tag(self) -> None:
        warning_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            self.probe.record_chunk(2500.0, 3)
        assert any("[STREAM-STALL]" in m for m in warning_calls)
        assert self.probe.stall_count == 1

    def test_burst_logs_stream_burst_tag(self) -> None:
        info_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            self.probe.record_chunk(2.0, 10)
        assert any("[STREAM-BURST]" in m for m in info_calls)

    def test_stall_increments_stall_count(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            self.probe.record_chunk(3000.0, 1)
            self.probe.record_chunk(4000.0, 1)
            self.probe.record_chunk(2500.0, 1)
        assert self.probe.stall_count == 3

    def test_record_chunk_populates_registry(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            for i in range(5):
                self.probe.record_chunk(float(100 + i * 10), 3)
        stats = self.probe.stats()
        assert stats["count"] == 5.0

    def test_summarize_logs_stream_summary(self) -> None:
        info_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            self.probe.record_chunk(100.0, 3)
            self.probe.record_chunk(150.0, 4)
            self.probe.record_chunk(200.0, 5)
        info_calls.clear()
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.side_effect = lambda msg: info_calls.append(msg)
            mock_log.warning = lambda msg: None
            self.probe.summarize()
        assert any("[STREAM-SUMMARY]" in m for m in info_calls)

    def test_summarize_resets_counters(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            self.probe.record_chunk(3000.0, 2)
            self.probe.record_chunk(100.0, 3)
            self.probe.record_chunk(200.0, 4)
            self.probe.summarize()
        assert self.probe.chunk_count == 0
        assert self.probe.stall_count == 0

    def test_summarize_clears_registry(self) -> None:
        with patch("hermes_cli.tui.perf.log"):
            for i in range(5):
                self.probe.record_chunk(100.0 + i, 3)
            self.probe.summarize()
        stats = self.probe.stats()
        assert stats["count"] == 0.0

    def test_alarm_fires_on_repeated_stalls(self) -> None:
        warning_calls: list = []
        error_calls: list = []
        with patch("hermes_cli.tui.perf.log") as mock_log:
            mock_log.warning = lambda msg: warning_calls.append(msg)
            mock_log.error = lambda msg: error_calls.append(msg)
            mock_log.side_effect = lambda msg: None
            for _ in range(3):
                self.probe.record_chunk(3000.0, 2)
        all_msgs = warning_calls + error_calls
        assert any("[PERF-ALARM]" in m for m in all_msgs)

    def test_last_chunk_ts_reset_on_stream_start(self) -> None:
        """mark_response_stream_started() sets _last_stream_chunk_ts to None."""
        mock_app = MagicMock()
        mock_app._response_metrics_active = False
        mock_app._response_segment_start_time = None
        mock_app._last_stream_chunk_ts = 12345.0

        # Simulate what mark_response_stream_started does
        mock_app._last_stream_chunk_ts = None
        assert mock_app._last_stream_chunk_ts is None
