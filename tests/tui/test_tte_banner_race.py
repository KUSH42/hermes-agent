"""Tests for R4-T-H1: STARTUP_BANNER_READY event gate syncs TTE worker
against StartupBannerWidget mount.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import pytest
from unittest.mock import MagicMock, patch

from rich.text import Text


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
    # Bind the real _handle_tte_producer_exc so logger.debug calls go through
    mock_self._handle_tte_producer_exc = lambda exc: HermesCLI._handle_tte_producer_exc(exc)
    return mock_self


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
                mock_self, "matrix", "test hero", {}
            )
        assert result is False
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("did not mount within 2s" in s for s in debug_msgs)
        mock_logger.warning.assert_not_called()

    def test_drain_latest_logs_debug_on_NoMatches(self):
        """_drain_latest logs DEBUG (not WARNING) when query_one raises NoMatches."""
        from cli import HermesCLI
        from textual.css.query import NoMatches

        mock_self = _make_cli_mock()
        mock_app = MagicMock()
        mock_app.query_one.side_effect = NoMatches()

        captured_fns: list = []

        def _capture(fn):
            captured_fns.append(fn)

        mock_app.call_from_thread.side_effect = _capture

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])),
            patch("cli.logger") as mock_logger,
            patch("time.sleep"),
        ):
            mock_event.wait.return_value = True
            HermesCLI._play_tte_in_output_panel(mock_self, "matrix", "hero", {})

            assert captured_fns, "call_from_thread should be called for preflight frame"
            # call_from_thread receives the async function — call it to get a coroutine
            asyncio.run(captured_fns[0]())

            debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
            assert any("vanished mid-stream" in s for s in debug_msgs)
            mock_logger.warning.assert_not_called()

    def test_frame_loop_swallows_CancelledError_at_debug(self):
        """concurrent.futures.CancelledError from call_from_thread is DEBUG, not WARNING.

        rendered_any is True because one frame was produced before cancellation.
        """
        from cli import HermesCLI

        mock_self = _make_cli_mock()
        mock_app = MagicMock()

        def _one_frame_then_cancel(*args, **kwargs):
            yield "frame1"
            raise concurrent.futures.CancelledError()

        with (
            patch("cli._hermes_app", mock_app),
            patch("hermes_cli.tui.widgets.STARTUP_BANNER_READY") as mock_event,
            patch(
                "hermes_cli.tui.tte_runner.iter_frames",
                side_effect=_one_frame_then_cancel,
            ),
            patch("cli.logger") as mock_logger,
            patch("time.sleep"),
        ):
            mock_event.wait.return_value = True
            result = HermesCLI._play_tte_in_output_panel(mock_self, "matrix", "hero", {})

        assert result is True, "rendered_any should be True (one frame produced)"
        debug_msgs = [str(c) for c in mock_logger.debug.call_args_list]
        assert any("cancelled at teardown" in s for s in debug_msgs)
        warning_msgs = [str(c) for c in mock_logger.warning.call_args_list]
        assert not any("TTE frame error" in s for s in warning_msgs), (
            "CancelledError must NOT reach the generic warning handler"
        )
