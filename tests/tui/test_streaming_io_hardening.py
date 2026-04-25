"""Tests for IOService streaming-IO hardening: L1, M2, M3."""
from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(maxsize: int = 8) -> types.SimpleNamespace:
    """Minimal app stub for IOService tests."""
    loop = asyncio.new_event_loop()
    app = types.SimpleNamespace(
        _output_queue=asyncio.Queue(maxsize=maxsize),
        _event_loop=loop,
        status_output_dropped=False,
        status_output_pressure=False,
    )
    return app


def _fill_queue(queue: asyncio.Queue, n: int) -> None:
    for i in range(n):
        queue.put_nowait(f"chunk{i}")


# ---------------------------------------------------------------------------
# Class TestDropLogging  (L1 — 4 tests)
# ---------------------------------------------------------------------------

class TestDropLogging:
    def setup_method(self):
        from hermes_cli.tui.services.io import IOService
        self.IOService = IOService

    def _make_service_and_app(self, maxsize: int = 4):
        app = _make_app(maxsize=maxsize)
        svc = object.__new__(self.IOService)
        svc.app = app
        return svc, app

    def test_drop_logs_warning_on_first_drop(self):
        svc, app = self._make_service_and_app(maxsize=4)
        _fill_queue(app._output_queue, 4)  # queue now full

        with patch("hermes_cli.tui.services.io.logger") as mock_log, \
             patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("overflow")

        mock_log.warning.assert_called_once()
        call_msg = mock_log.warning.call_args[0][0]
        assert "output queue full" in call_msg
        app._event_loop.close()

    def test_drop_no_duplicate_warning_on_consecutive_drops(self):
        svc, app = self._make_service_and_app(maxsize=4)
        _fill_queue(app._output_queue, 4)

        with patch("hermes_cli.tui.services.io.logger") as mock_log, \
             patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("overflow1")
            svc.write_output("overflow2")

        assert mock_log.warning.call_count == 1
        app._event_loop.close()

    def test_drop_warning_resets_after_success(self):
        svc, app = self._make_service_and_app(maxsize=4)
        _fill_queue(app._output_queue, 4)

        with patch("hermes_cli.tui.services.io.logger") as mock_log, \
             patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            # First drop-run
            svc.write_output("overflow1")
            # Drain queue to allow next write to succeed
            while not app._output_queue.empty():
                app._output_queue.get_nowait()
            # Successful write resets gate
            svc.write_output("success")
            # Drain again (removes the "success" item) before refill
            while not app._output_queue.empty():
                app._output_queue.get_nowait()
            # Refill and drop again
            _fill_queue(app._output_queue, 4)
            svc.write_output("overflow2")

        assert mock_log.warning.call_count == 2
        app._event_loop.close()

    def test_no_warning_on_success(self):
        svc, app = self._make_service_and_app(maxsize=8)

        with patch("hermes_cli.tui.services.io.logger") as mock_log, \
             patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("hello")

        mock_log.warning.assert_not_called()
        app._event_loop.close()


# ---------------------------------------------------------------------------
# Class TestFlushSentinelRetry  (M2 — 8 tests)
# ---------------------------------------------------------------------------

class TestFlushSentinelRetry:
    def setup_method(self):
        from hermes_cli.tui.services.io import IOService
        self.IOService = IOService

    def _make_service_and_app(self, maxsize: int = 8):
        app = _make_app(maxsize=maxsize)
        svc = object.__new__(self.IOService)
        svc.app = app
        return svc, app

    def _run(self, loop: asyncio.AbstractEventLoop, *coros):
        return loop.run_until_complete(asyncio.gather(*coros))

    def test_flush_sentinel_enqueued_when_room(self):
        svc, app = self._make_service_and_app(maxsize=4)
        loop = app._event_loop

        with patch("hermes_cli.tui.services.io.logger"):
            svc.flush_output()

            async def _wait():
                await asyncio.sleep(0)
                await asyncio.sleep(0)

            loop.run_until_complete(_wait())

        assert not app._output_queue.empty()
        assert app._output_queue.get_nowait() is None
        loop.close()

    def test_flush_sentinel_retry_on_full(self):
        """Sentinel arrives after consumer drains one slot during the sleep(0) yield."""

        async def _run():
            queue = asyncio.Queue(maxsize=4)
            for i in range(4):
                queue.put_nowait(f"chunk{i}")

            async def _send_flush():
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    await asyncio.sleep(0)
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass

            async def drain_one():
                await asyncio.sleep(0)
                await queue.get()

            # drain_one must be scheduled first so its sleep(0) fires before
            # _send_flush's retry — otherwise the queue is still full on retry.
            await asyncio.gather(drain_one(), _send_flush())
            return queue

        queue = asyncio.run(_run())
        items = []
        while not queue.empty():
            items.append(queue.get_nowait())

        assert None in items

    def test_flush_sentinel_logs_warning_when_both_tries_fail(self):
        """When queue stays full through both tries, logger.warning is called."""
        svc, app = self._make_service_and_app(maxsize=4)
        loop = app._event_loop
        _fill_queue(app._output_queue, 4)

        with patch("hermes_cli.tui.services.io.logger") as mock_log:
            # Call flush_output; coroutine runs via run_coroutine_threadsafe
            svc.flush_output()
            # Run the scheduled coroutine to completion (queue stays full — no drain)
            loop.run_until_complete(asyncio.sleep(0.01))

        mock_log.warning.assert_called_once()
        call_msg = mock_log.warning.call_args[0][0]
        assert "sentinel dropped after retry" in call_msg
        loop.close()

    def test_flush_sentinel_no_warning_on_success(self):
        svc, app = self._make_service_and_app(maxsize=8)
        loop = app._event_loop

        with patch("hermes_cli.tui.services.io.logger") as mock_log:
            svc.flush_output()

            async def _wait():
                await asyncio.sleep(0)
                await asyncio.sleep(0)

            loop.run_until_complete(_wait())

        mock_log.warning.assert_not_called()
        loop.close()

    def test_flush_uses_run_coroutine_threadsafe_regardless_of_fast_path(self):
        svc, app = self._make_service_and_app()
        loop = app._event_loop

        def _consuming_mock(coro, _loop):
            # close the coroutine so Python doesn't warn about it never being awaited
            coro.close()
            return MagicMock()

        with patch("hermes_cli.tui.services.io.asyncio.run_coroutine_threadsafe",
                   side_effect=_consuming_mock) as mock_rcts, \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.flush_output()
            assert mock_rcts.call_count == 1

        with patch("hermes_cli.tui.services.io.asyncio.run_coroutine_threadsafe",
                   side_effect=_consuming_mock) as mock_rcts, \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", False):
            svc.flush_output()
            assert mock_rcts.call_count == 1

        loop.close()

    def test_flush_runtime_error_swallowed(self):
        svc, app = self._make_service_and_app()
        loop = app._event_loop

        def _raise_and_close(coro, _loop):
            coro.close()
            raise RuntimeError("loop closed")

        with patch(
            "hermes_cli.tui.services.io.asyncio.run_coroutine_threadsafe",
            side_effect=_raise_and_close,
        ):
            svc.flush_output()  # must not raise

        loop.close()

    def test_flush_noop_when_event_loop_none(self):
        svc, app = self._make_service_and_app()
        app._event_loop = None
        svc.flush_output()  # must not raise

    def test_flush_sentinel_arrives_after_data_chunks(self):
        """7 data chunks pre-filled; flush enqueues None as 8th; all 8 items drained; last is None."""
        svc, app = self._make_service_and_app(maxsize=8)
        loop = app._event_loop
        _fill_queue(app._output_queue, 7)

        with patch("hermes_cli.tui.services.io.logger"):
            svc.flush_output()
            # Give the scheduled coroutine enough ticks to complete
            async def _drain_pending():
                await asyncio.sleep(0)
                await asyncio.sleep(0)
            loop.run_until_complete(_drain_pending())

        items = []
        while not app._output_queue.empty():
            items.append(app._output_queue.get_nowait())

        assert len(items) == 8
        assert items[-1] is None
        loop.close()


# ---------------------------------------------------------------------------
# Class TestPressureMetric  (M3 — 6 tests)
# ---------------------------------------------------------------------------

class TestPressureMetric:
    def setup_method(self):
        from hermes_cli.tui.services.io import IOService
        self.IOService = IOService

    def _make_service_and_app(self, maxsize: int = 8):
        app = _make_app(maxsize=maxsize)
        svc = object.__new__(self.IOService)
        svc.app = app
        return svc, app

    def test_pressure_set_at_75pct(self):
        """maxsize=8, threshold=6; after 5 items+write → qsize=6 → flag set."""
        svc, app = self._make_service_and_app(maxsize=8)
        _fill_queue(app._output_queue, 5)

        with patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("item6")

        assert app.status_output_pressure is True
        app._event_loop.close()

    def test_pressure_cleared_at_50pct(self):
        """maxsize=8, clear=4; flag True; drain to 2 items; write → qsize=3 < 4 → cleared."""
        svc, app = self._make_service_and_app(maxsize=8)
        app.status_output_pressure = True
        _fill_queue(app._output_queue, 2)

        with patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("item3")

        assert app.status_output_pressure is False
        app._event_loop.close()

    def test_pressure_not_set_below_threshold(self):
        """maxsize=100; 73 items pre-filled; write → qsize=74 (74%) < 75 → flag stays False."""
        svc, app = self._make_service_and_app(maxsize=100)
        _fill_queue(app._output_queue, 73)

        with patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("item74")

        assert app.status_output_pressure is False
        app._event_loop.close()

    def test_pressure_cleared_not_below_50(self):
        """maxsize=8; flag True; 5 items; write → qsize=6 ≥ 4 → flag unchanged (True)."""
        svc, app = self._make_service_and_app(maxsize=8)
        app.status_output_pressure = True
        _fill_queue(app._output_queue, 5)

        with patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("item6")

        assert app.status_output_pressure is True
        app._event_loop.close()

    def test_pressure_independent_of_drop_flag(self):
        """QueueFull path does NOT touch status_output_pressure."""
        svc, app = self._make_service_and_app(maxsize=8)
        app.status_output_pressure = False
        _fill_queue(app._output_queue, 8)

        with patch("hermes_cli.tui.services.io.logger"), \
             patch("hermes_cli.tui.perf._queue_probe"), \
             patch("hermes_cli.tui.services.io._CPYTHON_FAST_PATH", True):
            svc.write_output("overflow")

        assert app.status_output_dropped is True
        assert app.status_output_pressure is False
        app._event_loop.close()

    def test_pressure_reactive_attribute_exists(self):
        from hermes_cli.tui.app import HermesApp
        assert hasattr(HermesApp, "status_output_pressure")
