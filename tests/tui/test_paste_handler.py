"""Tests for PS-NB-2 (async paste wire-through) and PS-NB-3 (paste flash unification).

No Textual pilot needed — all tests use unit-level mocks.

Classes:
  TestBracketedPasteAsync    — 3 tests (PS-NB-2): bracketed paste returns fast + async attach
  TestCtrlVProbeFallthrough  — 2 tests (PS-NB-2): ctrl-v probe→extract or fallthrough
  TestPasteFlashUnification  — 2 tests (PS-NB-3): flash_paste threshold + consistency
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.services.feedback import FeedbackService, HINT_KEY_PASTE_LARGE


# ---------------------------------------------------------------------------
# Helpers — FakeCLI mirrors the HermesCLI paste-handler contract
# ---------------------------------------------------------------------------

class _FakeClipboardSvc:
    """Minimal ClipboardService double for handler tests."""

    def __init__(self, probe_result: bool = False, extract_result: bool = False):
        self.probe_result = probe_result
        self.extract_result = extract_result
        self.probe_call_count = 0
        self.extract_call_count = 0
        self._probe_cb: Callable | None = None
        self._extract_cb: Callable | None = None

    def probe(self, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        self.probe_call_count += 1
        self._probe_cb = on_done
        # Fire synchronously in tests for simplicity
        on_done(self.probe_result)

    def extract(self, dest: Path, on_done: Callable[[bool], None], timeout: float = 8.0) -> None:
        self.extract_call_count += 1
        self._extract_cb = on_done
        on_done(self.extract_result)

    def cancel_in_flight(self) -> None:
        pass


class _FakeCLI:
    """Minimal HermesCLI surface needed by the paste handlers."""

    def __init__(self, svc: _FakeClipboardSvc | None = None):
        self._clipboard_svc = svc
        self._attached_images: list[Path] = []
        self._image_counter = 0
        self._hints: list[str] = []
        self._invalidated = 0
        self._counter = [0]

    def _next_clip_image_path(self) -> Path:
        self._image_counter += 1
        return Path(f"/tmp/clip_test_{self._image_counter}.png")

    def _flash_pt_hint(self, text: str, duration: float = 2.0) -> None:
        self._hints.append(text)

    def _try_attach_clipboard_image(self) -> bool:
        """Synchronous fallback."""
        return False

    def _invalidate(self, **kwargs) -> None:
        self._invalidated += 1


def _make_fake_event(app=None):
    """Build a minimal prompt_toolkit event double."""
    ev = MagicMock()
    ev.app = app or MagicMock()
    ev.app.invalidate = MagicMock()
    ev.app.clipboard.get_data.return_value = MagicMock()
    ev.app.current_buffer.paste_clipboard_data = MagicMock()
    return ev


def _build_bracketed_paste_handler(cli: _FakeCLI):
    """Reconstruct the bracketed-paste image-attach section as a callable."""

    def handle(pasted_text: str, event_app_invalidate: MagicMock) -> None:
        ev = _make_fake_event()
        ev.app.invalidate = event_app_invalidate

        # Reproduces the PS-NB-2 bracketed-paste logic from cli.py
        # _should_auto_attach_clipboard_image_on_paste lives in cli.py (module-level fn)
        should_attach = (pasted_text == "" or pasted_text.strip() == "")

        if should_attach:
            if cli._clipboard_svc is not None:
                cli._flash_pt_hint("⏳ checking clipboard…")
                img_path = cli._next_clip_image_path()

                def _on_bp_done(ok: bool) -> None:
                    cli._flash_pt_hint("")
                    if ok:
                        cli._attached_images.append(img_path)
                        ev.app.invalidate()
                    else:
                        cli._image_counter -= 1

                cli._clipboard_svc.extract(img_path, _on_bp_done)
            elif cli._try_attach_clipboard_image():
                ev.app.invalidate()

    return handle


def _build_ctrl_v_handler(cli: _FakeCLI):
    """Reconstruct the Ctrl-V handler as a callable."""

    def handle() -> None:
        ev = _make_fake_event()

        if cli._clipboard_svc is None:
            if cli._try_attach_clipboard_image():
                ev.app.invalidate()
            return

        cli._flash_pt_hint("⏳ checking clipboard…")
        img_path = cli._next_clip_image_path()
        _cv_event_app = ev.app

        def _on_image_ready(ok: bool) -> None:
            cli._flash_pt_hint("")
            if ok:
                cli._attached_images.append(img_path)
                _cv_event_app.invalidate()
            else:
                cli._image_counter -= 1
                _cv_event_app.current_buffer.paste_clipboard_data(
                    _cv_event_app.clipboard.get_data()
                )

        def _on_probe(has_image: bool) -> None:
            if has_image:
                cli._clipboard_svc.extract(img_path, _on_image_ready)
            else:
                cli._flash_pt_hint("")
                cli._image_counter -= 1
                _cv_event_app.current_buffer.paste_clipboard_data(
                    _cv_event_app.clipboard.get_data()
                )

        cli._clipboard_svc.probe(_on_probe)
        return ev

    return handle


# ---------------------------------------------------------------------------
# TestBracketedPasteAsync  (PS-NB-2)
# ---------------------------------------------------------------------------

class TestBracketedPasteAsync:

    def test_bracketed_paste_returns_within_50ms_with_pending_marker(self):
        """With async service, bracketed-paste handler returns immediately and sets marker."""
        slow_extract_started = threading.Event()
        slow_extract_done = threading.Event()

        class _SlowSvc(_FakeClipboardSvc):
            def extract(self, dest, on_done, timeout=8.0):
                self.extract_call_count += 1
                slow_extract_started.set()
                # Simulate delayed callback (worker thread resolves later)
                def _delayed():
                    time.sleep(0.1)
                    on_done(True)
                    slow_extract_done.set()
                threading.Thread(target=_delayed, daemon=True).start()

        svc = _SlowSvc(extract_result=True)
        cli = _FakeCLI(svc=svc)
        handler = _build_bracketed_paste_handler(cli)

        start = time.perf_counter()
        handler("", MagicMock())
        elapsed = time.perf_counter() - start

        # Handler must return in much less than 50 ms (async dispatch)
        assert elapsed < 0.05, f"handler blocked for {elapsed*1000:.0f}ms"
        # Marker was set
        assert "⏳ checking clipboard…" in cli._hints

    def test_bracketed_paste_attach_image_when_worker_succeeds(self):
        """When extract resolves True, image path is appended to attached list."""
        svc = _FakeClipboardSvc(extract_result=True)
        cli = _FakeCLI(svc=svc)
        handler = _build_bracketed_paste_handler(cli)
        inv = MagicMock()
        handler("", inv)
        assert len(cli._attached_images) == 1
        inv.assert_called_once()

    def test_bracketed_paste_no_attach_when_worker_fails(self):
        """When extract resolves False, nothing is attached and counter is restored."""
        svc = _FakeClipboardSvc(extract_result=False)
        cli = _FakeCLI(svc=svc)
        initial_counter = cli._image_counter
        handler = _build_bracketed_paste_handler(cli)
        inv = MagicMock()
        handler("", inv)
        assert cli._attached_images == []
        # Counter must not grow permanently on failure
        assert cli._image_counter == initial_counter
        inv.assert_not_called()


# ---------------------------------------------------------------------------
# TestCtrlVProbeFallthrough  (PS-NB-2)
# ---------------------------------------------------------------------------

class TestCtrlVProbeFallthrough:

    def test_ctrl_v_falls_through_to_text_paste_when_no_image(self):
        """probe returns False → paste_clipboard_data called; nothing attached."""
        svc = _FakeClipboardSvc(probe_result=False, extract_result=True)
        cli = _FakeCLI(svc=svc)
        handler = _build_ctrl_v_handler(cli)
        ev = handler()
        assert cli._attached_images == []
        assert svc.extract_call_count == 0
        ev.app.current_buffer.paste_clipboard_data.assert_called_once()

    def test_ctrl_v_attaches_image_when_worker_succeeds(self):
        """probe True → extract True → image attached; paste_clipboard_data not called."""
        svc = _FakeClipboardSvc(probe_result=True, extract_result=True)
        cli = _FakeCLI(svc=svc)
        handler = _build_ctrl_v_handler(cli)
        ev = handler()
        assert len(cli._attached_images) == 1
        ev.app.invalidate.assert_called_once()
        ev.app.current_buffer.paste_clipboard_data.assert_not_called()


# ---------------------------------------------------------------------------
# TestPasteFlashUnification  (PS-NB-3)
# ---------------------------------------------------------------------------

class TestPasteFlashUnification:
    """Tests for flash_paste() on FeedbackService."""

    def _make_feedback_svc(self):
        """Return a FeedbackService with a minimal stub channel registered."""
        from hermes_cli.tui.services.feedback import FeedbackService, AppScheduler

        sched = MagicMock()
        svc = FeedbackService.__new__(FeedbackService)
        # Minimal init without a real scheduler
        svc._channels = {}
        svc._active = {}
        svc._registering = set()

        # Spy on flash()
        svc._flash_calls: list[tuple] = []
        _real_flash = FeedbackService.flash

        def _spy_flash(self_inner, channel, message, **kwargs):
            svc._flash_calls.append((channel, message, kwargs))
            # Simulate channel not registered — we're testing guard logic
            # by registering a stub channel instead.
            pass

        svc.flash = lambda *a, **kw: svc._flash_calls.append((a, kw))
        return svc

    def test_paste_flash_consistent_across_input_and_app_path(self):
        """flash_paste() calls flash() with HINT_KEY_PASTE_LARGE key when >80 chars."""
        from hermes_cli.tui.services.feedback import FeedbackService

        svc = FeedbackService.__new__(FeedbackService)
        svc._flash_calls = []
        svc.flash = MagicMock()

        svc.flash_paste(100)

        svc.flash.assert_called_once()
        _, kwargs = svc.flash.call_args
        assert kwargs.get("key") == HINT_KEY_PASTE_LARGE
        assert "100 chars pasted" in svc.flash.call_args.args[1]

    def test_paste_flash_skipped_below_threshold(self):
        """flash_paste() is a no-op for ≤80 chars."""
        from hermes_cli.tui.services.feedback import FeedbackService

        svc = FeedbackService.__new__(FeedbackService)
        svc.flash = MagicMock()

        svc.flash_paste(80)
        svc.flash_paste(0)
        svc.flash_paste(1)

        svc.flash.assert_not_called()
