"""Tests for TTE playback approach C: pre-render + loop-driven set_interval.

Covers:
- STARTUP_BANNER_READY gate (widget lifecycle)
- CLI worker early-exit paths
- _tick NoMatches handling
- CancelledError severity routing
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import pytest
from unittest.mock import MagicMock, patch

from rich.text import Text


def _tte_cfg(cli_module, **overrides):
    data = {
        "effect_name": "matrix",
        "params": {},
        "max_wall_s": 30.0,
        "max_frames": 3000,
        "fps": 60,
    }
    data.update(overrides)
    return cli_module._StartupTteConfig(**data)


@pytest.fixture(autouse=True)
def reset_startup_banner_event():
    """Reset module-level STARTUP_BANNER_READY before/after each test."""
    from hermes_cli.tui.widgets import STARTUP_BANNER_READY
    STARTUP_BANNER_READY.clear()
    yield
    STARTUP_BANNER_READY.clear()


# ---------------------------------------------------------------------------
# Widget lifecycle — event set/clear
# ---------------------------------------------------------------------------

class TestStartupBannerEventLifecycle:
    @pytest.mark.asyncio
    async def test_startup_banner_sets_event_on_mount(self):
        """on_mount sets STARTUP_BANNER_READY; event is clear before mount."""
        from hermes_cli.tui.widgets import STARTUP_BANNER_READY, StartupBannerWidget
        from textual.app import App, ComposeResult

        class _Host(App):
            def compose(self) -> ComposeResult:
                yield StartupBannerWidget()

        assert not STARTUP_BANNER_READY.is_set(), "event should be clear before app starts"
        async with _Host().run_test():
            assert STARTUP_BANNER_READY.is_set(), "event should be set after widget mounts"

    @pytest.mark.asyncio
    async def test_startup_banner_clears_event_on_unmount(self):
        """on_unmount clears STARTUP_BANNER_READY (hot-reload safety)."""
        from hermes_cli.tui.widgets import STARTUP_BANNER_READY, StartupBannerWidget
        from textual.app import App, ComposeResult

        class _Host(App):
            def compose(self) -> ComposeResult:
                yield StartupBannerWidget()

        async with _Host().run_test():
            assert STARTUP_BANNER_READY.is_set()
        # app has shut down (on_unmount fired)
        assert not STARTUP_BANNER_READY.is_set(), "event should be clear after widget unmounts"


# ---------------------------------------------------------------------------
# CLI worker gate
# ---------------------------------------------------------------------------

def _make_cli_mock() -> MagicMock:
    """Minimal mock for HermesCLI instance used as 'self' in the worker."""
    from cli import HermesCLI
    mock_self = MagicMock()
    mock_self._build_startup_banner_template.return_value = None
    mock_self._render_startup_banner_text.return_value = Text("banner")
    mock_self._handle_tte_producer_exc = lambda exc: HermesCLI._handle_tte_producer_exc(exc)
    return mock_self


def _make_mock_app_with_timer():
    """Return (mock_app, tick_fn_ref, playback_unblock) for set_interval tests.

    call_from_thread immediately invokes the passed callable.
    set_interval captures _tick into tick_fn_ref[0] and installs a timer that
    the test controls — calling tick_fn_ref[0]() drives one display tick.
    """
    mock_app = MagicMock()
    tick_fn_ref: list = []
    timer_mock = MagicMock()

    def _capture_set_interval(interval, fn):
        tick_fn_ref.append(fn)
        return timer_mock

    mock_app.set_interval.side_effect = _capture_set_interval
    # call_from_thread(async_fn) — run it synchronously via asyncio.run
    mock_app.call_from_thread.side_effect = lambda fn: asyncio.run(fn())

    return mock_app, tick_fn_ref, timer_mock


class TestTTEWorkerWaitGate:
    def test_play_tte_returns_false_when_banner_never_mounts(self):
        """When STARTUP_BANNER_READY.wait times out, returns False with DEBUG (no WARNING)."""
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = MagicMock()
        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("cli.logger") as mock_logger,
        ):
            mock_event.wait.return_value = False
            result = HermesCLI._play_tte_in_output_panel(
                mock_self, _tte_cfg(__import__("cli")), "test hero"
            )
        assert result is False
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("did not mount within 2s" in s for s in debug_msgs)
        mock_logger.warning.assert_not_called()

    def test_play_tte_returns_false_when_no_frames_produced(self):
        """Returns False (rendered_any=False) when iter_frames yields nothing."""
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = MagicMock()
        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])),
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self, _tte_cfg(__import__("cli")), "hero"
            )
        assert result is False

    def test_tick_logs_debug_on_NoMatches(self):
        """_tick logs DEBUG (not WARNING) when query_one raises NoMatches."""
        from cli import HermesCLI
        from textual.css.query import NoMatches

        mock_self = _make_cli_mock()
        mock_app, tick_fn_ref, timer_mock = _make_mock_app_with_timer()
        mock_app.query_one.side_effect = NoMatches()

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["frame1"])),
            patch("cli.logger") as mock_logger,
        ):
            mock_event.wait.return_value = True

            result_ref: list = []
            done = threading.Event()

            def _run():
                result_ref.append(
                    HermesCLI._play_tte_in_output_panel(
                        mock_self, _tte_cfg(__import__("cli")), "hero"
                    )
                )
                done.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # Wait for timer to be installed, then fire one tick (NoMatches → sets playback_done)
            for _ in range(50):
                if tick_fn_ref:
                    break
                import time; time.sleep(0.01)
            assert tick_fn_ref, "set_interval should have been called"
            asyncio.run(tick_fn_ref[0]())

            done.wait(timeout=3.0)

        assert result_ref and result_ref[0] is True, "rendered_any should be True (frames produced)"
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("vanished mid-tick" in s for s in debug_msgs)
        mock_logger.warning.assert_not_called()

    def test_frame_loop_swallows_CancelledError_at_debug(self):
        """concurrent.futures.CancelledError from iter_frames is DEBUG, not WARNING.

        rendered_any is False because CancelledError fires before any frame is appended.
        """
        from cli import HermesCLI

        mock_self = _make_cli_mock()
        mock_app = MagicMock()

        def _cancel_immediately(*args, **kwargs):
            raise concurrent.futures.CancelledError()
            yield  # make it a generator

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch(
                "hermes_cli.tui.tte_runner.iter_frames",
                side_effect=_cancel_immediately,
            ),
            patch("cli.logger") as mock_logger,
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self,
                _tte_cfg(__import__("cli")),
                "hero",
            )

        assert result is False, "rendered_any should be False (cancelled before any frame)"
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("cancelled at teardown" in s for s in debug_msgs)
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert not any("TTE frame error" in s for s in warning_msgs), (
            "CancelledError must NOT reach the generic warning handler"
        )

    def test_tick_stops_timer_when_frames_exhausted(self):
        """Timer is stopped after all frames are consumed."""
        from cli import HermesCLI

        mock_self = _make_cli_mock()
        mock_app, tick_fn_ref, timer_mock = _make_mock_app_with_timer()
        widget_mock = MagicMock()
        mock_app.query_one.return_value = widget_mock

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["f1", "f2"])),
        ):
            mock_event.wait.return_value = True

            done = threading.Event()

            def _run():
                HermesCLI._play_tte_in_output_panel(
                    mock_self, _tte_cfg(__import__("cli")), "hero"
                )
                done.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            for _ in range(50):
                if tick_fn_ref:
                    break
                import time; time.sleep(0.01)
            assert tick_fn_ref

            # 2 anim frames + 1 appended static = 3 total; drain all + one extra to trigger stop
            for _ in range(4):
                asyncio.run(tick_fn_ref[0]())

            done.wait(timeout=3.0)

        timer_mock.stop.assert_called()

    def test_prerender_respects_max_frames_cap(self):
        """Pre-render stops at max_frames even if iter_frames yields more."""
        from cli import HermesCLI

        mock_self = _make_cli_mock()
        mock_app = MagicMock()
        mock_app.call_from_thread.side_effect = lambda fn: asyncio.run(fn())

        timer_mock = MagicMock()
        tick_fn_ref: list = []
        mock_app.set_interval.side_effect = lambda i, fn: (tick_fn_ref.append(fn), timer_mock)[1]

        widget_mock = MagicMock()
        mock_app.query_one.return_value = widget_mock

        def _many_frames(*a, **kw):
            for i in range(100):
                yield f"frame{i}"

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", side_effect=_many_frames),
        ):
            mock_event.wait.return_value = True

            done = threading.Event()
            result_ref: list = []

            def _run():
                result_ref.append(
                    HermesCLI._play_tte_in_output_panel(
                        mock_self, _tte_cfg(__import__("cli"), max_frames=5), "hero"
                    )
                )
                done.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            for _ in range(50):
                if tick_fn_ref:
                    break
                import time; time.sleep(0.01)

            # drain 5 anim + 1 static + 1 stop tick
            for _ in range(7):
                asyncio.run(tick_fn_ref[0]())

            done.wait(timeout=3.0)

        assert result_ref and result_ref[0] is True
        # widget.set_frame called exactly 6 times (5 anim + 1 static)
        assert widget_mock.set_frame.call_count == 6
