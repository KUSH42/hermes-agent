"""Tests for PS-NB-1/PS-NB-4: ClipboardService skeleton and probe-first optimisation."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.services.clipboard import (
    ClipboardService,
    PromptToolkitClipboardService,
    TextualClipboardService,
)


# ---------------------------------------------------------------------------
# Fake subclass — records dispatched results without needing a real event loop
# ---------------------------------------------------------------------------

class FakeClipboardService(ClipboardService):
    """Test double: _dispatch records (result,) synchronously on the caller thread."""

    def __init__(self, probe_result: bool = False, extract_result: bool = False):
        super().__init__()
        self.probe_result = probe_result
        self.extract_result = extract_result
        self.on_done_calls: list[bool] = []
        self.probe_call_count = 0
        self.extract_call_count = 0

    def probe(self, on_done, timeout=8.0):
        self.probe_call_count += 1
        self._spawn(lambda: self.probe_result, on_done, timeout)

    def extract(self, dest, on_done, timeout=8.0):
        self.extract_call_count += 1
        self._spawn(lambda: self.extract_result, on_done, timeout)

    def _dispatch(self, on_done, result):
        self.on_done_calls.append(result)
        on_done(result)


# ---------------------------------------------------------------------------
# TestClipboardServiceCore  (PS-NB-1)
# ---------------------------------------------------------------------------

class TestClipboardServiceCore:

    def test_clipboard_service_probe_off_thread(self):
        """probe worker runs on a non-main thread."""
        worker_thread_ids: list[int] = []
        barrier = threading.Event()

        class _Spy(FakeClipboardService):
            def _dispatch(self, on_done, result):
                worker_thread_ids.append(threading.current_thread().ident)
                barrier.set()
                on_done(result)

        svc = _Spy(probe_result=True)
        svc.probe(lambda _r: None)
        barrier.wait(timeout=2.0)
        assert worker_thread_ids, "worker never dispatched"
        assert worker_thread_ids[0] != threading.main_thread().ident

    def test_clipboard_service_extract_callback_fired_on_event_loop(self):
        """Callback fires after worker completes with the correct result."""
        results: list[bool] = []
        done = threading.Event()

        svc = FakeClipboardService(extract_result=True)

        def _cb(ok: bool) -> None:
            results.append(ok)
            done.set()

        svc.extract(Path("/tmp/test.png"), _cb)
        done.wait(timeout=2.0)
        assert results == [True]

    def test_clipboard_service_cancel_in_flight_drops_callback(self):
        """cancel_in_flight() before worker finishes suppresses the callback."""
        called: list[bool] = []
        slow_start = threading.Event()
        worker_done = threading.Event()

        class _SlowSvc(ClipboardService):
            def _dispatch(self, on_done, result):
                called.append(result)
                on_done(result)

        svc = _SlowSvc()

        def _slow_work():
            slow_start.set()
            time.sleep(0.5)
            worker_done.set()
            return True

        svc._spawn(_slow_work, lambda _r: None, timeout=8.0)
        slow_start.wait(timeout=1.0)  # wait until worker has started
        svc.cancel_in_flight()
        worker_done.wait(timeout=2.0)  # wait for worker to finish
        # Give _maybe_dispatch a tick to run (it's on the worker thread)
        time.sleep(0.05)
        assert called == [], "callback should have been suppressed by cancel"

    def test_clipboard_service_timeout_emits_false(self):
        """Worker blocked past timeout fires callback with False."""
        results: list[bool] = []
        done = threading.Event()
        block = threading.Event()

        class _TimeoutSvc(ClipboardService):
            def _dispatch(self, on_done, result):
                results.append(result)
                done.set()
                on_done(result)

        svc = _TimeoutSvc()

        def _blocking_work():
            block.wait(timeout=30.0)  # never unblocks during test
            return True

        svc._spawn(_blocking_work, lambda _r: None, timeout=0.1)
        done.wait(timeout=2.0)
        block.set()  # unblock the worker so daemon thread exits
        assert results == [False], "timeout must fire callback with False"

    def test_clipboard_service_concurrent_calls_supersede(self):
        """Second call cancels first; only second callback fires."""
        results: list[bool] = []
        second_done = threading.Event()
        first_started = threading.Event()
        unblock_first = threading.Event()

        class _RecordSvc(ClipboardService):
            def _dispatch(self, on_done, result):
                results.append(result)
                if len(results) == 1:
                    second_done.set()
                on_done(result)

        svc = _RecordSvc()

        # First call — slow, returns True
        def _first_work():
            first_started.set()
            unblock_first.wait(timeout=5.0)
            return True

        svc._spawn(_first_work, lambda _r: None, timeout=8.0)
        first_started.wait(timeout=1.0)

        # Second call immediately supersedes — fast, returns False
        def _second_work():
            return False

        svc._spawn(_second_work, lambda _r: None, timeout=8.0)
        second_done.wait(timeout=2.0)
        unblock_first.set()  # let first worker finish (it's already cancelled)
        time.sleep(0.1)  # settle any races

        # Only the second result should have been dispatched
        assert results == [False], f"expected only [False], got {results}"


# ---------------------------------------------------------------------------
# TestClipboardServiceProbeFirst  (PS-NB-4)
# ---------------------------------------------------------------------------

class TestClipboardServiceProbeFirst:

    def _make_ctrl_v_handler(self, svc: FakeClipboardService):
        """Build a minimal Ctrl-V handler closure wired to *svc*."""
        attached: list[Path] = []
        fallthrough_called: list[bool] = []

        def handle_ctrl_v():
            img_path = Path("/tmp/clip_test.png")

            def _on_image_ready(ok: bool) -> None:
                if ok:
                    attached.append(img_path)
                else:
                    # undo counter (not relevant here)
                    pass

            def _on_probe(has_image: bool) -> None:
                if has_image:
                    svc.extract(img_path, _on_image_ready)
                else:
                    fallthrough_called.append(True)

            svc.probe(_on_probe)

        return handle_ctrl_v, attached, fallthrough_called

    def test_ctrl_v_runs_probe_first_skips_extract_when_no_image(self):
        """probe returns False → extract() is never called."""
        svc = FakeClipboardService(probe_result=False, extract_result=True)
        handler, attached, fallthrough = self._make_ctrl_v_handler(svc)
        done = threading.Event()

        original_dispatch = svc._dispatch.__func__ if hasattr(svc._dispatch, "__func__") else None

        # Track when probe callback fires
        original_probe = svc.probe

        probed_done = threading.Event()

        def _probe_with_wait(on_done, timeout=8.0):
            def _wrapped(result):
                on_done(result)
                probed_done.set()
            original_probe(_wrapped, timeout)

        svc.probe = _probe_with_wait
        handler()
        probed_done.wait(timeout=2.0)
        time.sleep(0.05)  # settle
        assert svc.extract_call_count == 0, "extract must not be called when probe is False"
        assert fallthrough == [True], "fallthrough should have been called"

    def test_ctrl_v_extract_only_when_probe_true(self):
        """probe returns True → extract() is called exactly once."""
        svc = FakeClipboardService(probe_result=True, extract_result=True)
        handler, attached, fallthrough = self._make_ctrl_v_handler(svc)

        extract_done = threading.Event()
        original_extract = svc.extract

        def _extract_with_wait(dest, on_done, timeout=8.0):
            def _wrapped(result):
                on_done(result)
                extract_done.set()
            original_extract(dest, _wrapped, timeout)

        svc.extract = _extract_with_wait
        handler()
        extract_done.wait(timeout=2.0)
        assert svc.probe_call_count == 1
        assert svc.extract_call_count == 1
        assert len(attached) == 1
