"""Tests for startup TTE animation: STARTUP_BANNER_READY gate + suspend-based playback."""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import pytest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, PropertyMock

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
# CLI worker gate + suspend-based animation path
# ---------------------------------------------------------------------------

def _make_cli_mock() -> MagicMock:
    """Minimal mock for HermesCLI instance used as 'self' in the worker."""
    from cli import HermesCLI
    mock_self = MagicMock()
    mock_self._build_startup_banner_template.return_value = None
    mock_self._render_startup_banner_text.return_value = Text("banner")
    mock_self._startup_banner_template = None
    mock_self._startup_banner_static = None
    mock_self._first_input_seen = threading.Event()
    mock_self._first_input_seen.set()  # don't block hold
    mock_self._ensure_startup_banner_artefacts = MagicMock()
    mock_self._splice_startup_banner_frame = MagicMock(return_value=Text("spliced"))
    mock_self._hero_ansi_colored = MagicMock(return_value="hero_ansi")
    # Bind the real _handle_tte_producer_exc so logger.debug calls go through
    mock_self._handle_tte_producer_exc = lambda exc: HermesCLI._handle_tte_producer_exc(exc)
    return mock_self


def _make_app_mock_with_loop(loop: asyncio.AbstractEventLoop) -> MagicMock:
    """App mock wired to a real event loop with a no-op suspend context manager."""
    mock_app = MagicMock()
    mock_app._event_loop = loop
    mock_app._suspend_busy = False
    mock_app.is_running = True
    # suspend() must be a sync context manager (contextlib-style)
    @contextmanager
    def _noop_suspend():
        yield
    mock_app.suspend = _noop_suspend
    return mock_app


@pytest.fixture
def bg_event_loop():
    """Run an asyncio event loop in a background thread for the duration of the test."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


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

    def test_play_tte_returns_false_when_no_event_loop(self):
        """Returns False immediately when app._event_loop is None."""
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = MagicMock()
        mock_app._event_loop = None

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("cli.logger") as mock_logger,
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self, _tte_cfg(__import__("cli")), "hero"
            )
        assert result is False
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("event loop not available" in s for s in debug_msgs)

    def test_play_tte_skips_when_suspend_busy(self, bg_event_loop):
        """When _suspend_busy is True, animation is skipped and returns False."""
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = _make_app_mock_with_loop(bg_event_loop)
        mock_app._suspend_busy = True

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("cli.logger") as mock_logger,
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self, _tte_cfg(__import__("cli")), "hero"
            )
        assert result is False
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("suspend_busy" in s for s in debug_msgs)

    def test_suspend_path_renders_frames(self, bg_event_loop):
        """Animation runs in executor; returns True when frames are produced."""
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = _make_app_mock_with_loop(bg_event_loop)

        def _two_frames(*args, **kwargs):
            yield "frame1_ansi"
            yield "frame2_ansi"

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", side_effect=_two_frames),
            patch("sys.stdout"),
            patch("cli.logger"),
            patch("time.sleep"),
            patch("rich.console.Console"),
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self, _tte_cfg(__import__("cli")), "hero"
            )
        assert result is True

    def test_frame_loop_swallows_CancelledError_at_debug(self, bg_event_loop):
        """CancelledError from iter_frames is logged at DEBUG, not WARNING.

        rendered_any is True because one frame was produced before cancellation.
        """
        from cli import HermesCLI
        mock_self = _make_cli_mock()
        mock_app = _make_app_mock_with_loop(bg_event_loop)

        def _one_frame_then_cancel(*args, **kwargs):
            yield "frame1"
            raise concurrent.futures.CancelledError()

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True),
            patch("hermes_cli.tui.tte_runner.iter_frames", side_effect=_one_frame_then_cancel),
            patch("sys.stdout"),
            patch("cli.logger") as mock_logger,
            patch("time.sleep"),
            patch("rich.console.Console"),
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(
                mock_self,
                _tte_cfg(__import__("cli")),
                "hero",
            )

        assert result is True, "rendered_any should be True (one frame produced)"
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("cancelled at teardown" in s for s in debug_msgs)
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert not any("TTE frame error" in s for s in warning_msgs), (
            "CancelledError must NOT reach the generic warning handler"
        )
