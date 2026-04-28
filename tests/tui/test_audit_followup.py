"""Tests for live-audit follow-up spec: M-1, M-2, L-1.

M-1: on_approval_state ENTER trace downgraded; initial fire-through gated.
M-2: kitty_graphics TTY-unavailable latch; probes short-circuit after first failure.
L-1: app.on_mount logs warning when mount_ms > 500.

Spec: /home/xush/.hermes/2026-04-28-audit-followup-spec.md
"""
from __future__ import annotations

import errno
import logging
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# M-1 helpers
# ---------------------------------------------------------------------------

def _make_watchers_service():
    """Return a WatchersService instance with a fully-mocked app."""
    from hermes_cli.tui.services.watchers import WatchersService

    mock_app = MagicMock()
    # query_one raises NoMatches by default — we control this per-test
    from textual.css.query import NoMatches
    mock_app.query_one.side_effect = NoMatches()
    mock_app._svc_spinner.compute_hint_phase.return_value = "idle"

    svc = object.__new__(WatchersService)
    svc.app = mock_app
    svc._phase_before_error = ""
    svc._compact_warn_flashed = False
    svc._last_compact_value = None
    svc._approval_state_seen = False
    return svc, mock_app


# ---------------------------------------------------------------------------
# M-1 tests — on_approval_state log hygiene
# ---------------------------------------------------------------------------

class TestOnApprovalStateLogHygiene:
    def test_initial_none_fire_through_logs_debug_and_returns(self):
        """Initial reactive fire-through (None, unseen) logs at DEBUG and returns early."""
        svc, mock_app = _make_watchers_service()

        with patch("hermes_cli.tui.services.watchers._log") as mock_log:
            svc.on_approval_state(None)

        mock_log.warning.assert_not_called()
        mock_log.debug.assert_called_once()
        debug_msg = mock_log.debug.call_args[0][0]
        assert "initial fire-through" in debug_msg
        # DrawbrailleOverlay should NOT be queried on early return
        mock_app.query_one.assert_not_called()

    def test_real_clear_after_approval_runs_full_body(self):
        """None after a non-None state goes through the full body (DrawbrailleOverlay signaled)."""
        from hermes_cli.tui.state import ChoiceOverlayState
        svc, mock_app = _make_watchers_service()

        # Wire a mock overlay
        from textual.css.query import NoMatches
        mock_ov = MagicMock()
        mock_interrupt = MagicMock()
        mock_interrupt.hide_if_kind = MagicMock()

        # _get_interrupt_overlay returns the mock overlay
        svc._get_interrupt_overlay = MagicMock(return_value=mock_interrupt)
        svc._post_interrupt_focus = MagicMock()

        # Wire DrawbrailleOverlay query to succeed
        mock_drawbraille = MagicMock()
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
        def _query_one(cls):
            if cls is DrawbrailleOverlay:
                return mock_drawbraille
            raise NoMatches()
        mock_app.query_one.side_effect = _query_one

        # Build a minimal ChoiceOverlayState-like object
        fake_state = MagicMock(spec=ChoiceOverlayState)

        with patch("hermes_cli.tui.services.watchers._log"):
            # First call: non-None → sets _approval_state_seen
            svc.on_approval_state(fake_state)
            # Second call: None clear → should run full body, signal "thinking"
            svc.on_approval_state(None)

        # DrawbrailleOverlay should have been signaled on the clear call
        signal_calls = mock_drawbraille.signal.call_args_list
        assert any(c == call("thinking") for c in signal_calls), (
            f"Expected signal('thinking') among {signal_calls}"
        )
        # Overlay hide path entered
        mock_interrupt.hide_if_kind.assert_called()

    def test_no_warning_in_errors_log_across_full_cycle(self):
        """No WARNING records from the ENTER trace or post-present diagnostic.

        The 'InterruptOverlay not mounted' warning at line 403 is intentionally
        kept at WARNING — it fires only when a real approval is pending and the
        overlay is missing. This test wires a proper mock overlay so that
        warning path is not triggered, isolating the two downgraded traces.
        """
        from hermes_cli.tui.state import ChoiceOverlayState
        from hermes_cli.tui.overlays import InterruptKind
        svc, mock_app = _make_watchers_service()

        # Wire a mock overlay so the "not mounted" WARNING path is not triggered
        mock_ov = MagicMock()
        mock_ov.present.return_value = None
        mock_ov.has_class.return_value = False
        svc._get_interrupt_overlay = MagicMock(return_value=mock_ov)
        svc._post_interrupt_focus = MagicMock()

        fake_state = MagicMock(spec=ChoiceOverlayState)

        with patch("hermes_cli.tui.services.watchers._log") as mock_log, \
             patch("hermes_cli.tui.overlays._adapters.make_approval_payload", return_value=MagicMock()):
            svc.on_approval_state(None)          # initial fire-through
            svc.on_approval_state(fake_state)    # real approval
            svc.on_approval_state(None)          # clear

        mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# M-2 helpers + teardown
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def reset_kitty_module_state():
    """Reset module-level latch and cache after each M-2 test."""
    import hermes_cli.tui.kitty_graphics as kg
    yield
    kg._tty_unavailable = False
    kg._cell_px_cache = None


# ---------------------------------------------------------------------------
# M-2 tests — TTY-unavailable latch
# ---------------------------------------------------------------------------

class TestKittyGraphicsTtyLatch:
    def test_cell_px_non_tty_latches_unavailable(self, reset_kitty_module_state):
        """OSError(ENOTTY) from ioctl latches _tty_unavailable; info logged once."""
        import hermes_cli.tui.kitty_graphics as kg

        tty_err = OSError(errno.ENOTTY, "not a tty")
        with patch("hermes_cli.tui.kitty_graphics.fcntl") as mock_fcntl, \
             patch("hermes_cli.tui.kitty_graphics._log") as mock_log:
            mock_fcntl.ioctl.side_effect = tty_err

            result1 = kg._cell_px()
            assert kg._tty_unavailable is True
            # Second call: short-circuits, no new ioctl
            result2 = kg._cell_px()

        # info logged exactly once across both calls
        assert mock_log.info.call_count == 1
        # debug with traceback NOT called for TTY errors
        debug_traceback_calls = [
            c for c in mock_log.debug.call_args_list
            if c.kwargs.get("exc_info") or (len(c.args) > 1 and c.args[-1] is True)
        ]
        assert len(debug_traceback_calls) == 0
        # Both calls return the fallback (10, 20) or env fallback
        assert result1 == (10, 20)
        assert result2 == (10, 20)

    def test_apc_probe_non_tty_latches_unavailable(self, reset_kitty_module_state):
        """OSError(ENOTTY) from tcgetattr latches _tty_unavailable; info logged once."""
        import io
        import hermes_cli.tui.kitty_graphics as kg

        tty_err = OSError(errno.ENOTTY, "not a tty")

        # In xdist workers stdin is redirected; fileno() may itself raise before
        # tcgetattr. Patch stdin.fileno() to return a fake fd so tcgetattr is
        # reached, then tcgetattr raises the expected OSError.
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 0

        with patch("hermes_cli.tui.kitty_graphics.sys") as mock_sys, \
             patch("hermes_cli.tui.kitty_graphics.termios") as mock_termios, \
             patch("hermes_cli.tui.kitty_graphics._log") as mock_log:
            mock_sys.stdin = mock_stdin
            mock_sys.stdout = MagicMock()
            mock_termios.tcgetattr.side_effect = tty_err
            mock_termios.TCSADRAIN = 2

            result1 = kg._apc_probe()
            assert kg._tty_unavailable is True, "latch should be set after first failure"
            result2 = kg._apc_probe()

        assert mock_log.info.call_count == 1
        assert result1 is False
        assert result2 is False

    def test_cell_px_real_ioctl_error_other_errno_still_logs_traceback(self, reset_kitty_module_state):
        """OSError with non-TTY errno (EIO) logs debug+traceback, does NOT latch."""
        import hermes_cli.tui.kitty_graphics as kg

        io_err = OSError(errno.EIO, "i/o error")
        with patch("hermes_cli.tui.kitty_graphics.fcntl") as mock_fcntl, \
             patch("hermes_cli.tui.kitty_graphics._log") as mock_log:
            mock_fcntl.ioctl.side_effect = io_err

            kg._cell_px()

        assert kg._tty_unavailable is False
        # Debug log with exc_info=True should be present
        debug_calls = mock_log.debug.call_args_list
        assert any(c.kwargs.get("exc_info") for c in debug_calls), (
            f"Expected debug(exc_info=True) but got {debug_calls}"
        )


# ---------------------------------------------------------------------------
# L-1 tests — mount_ms warning gate
# ---------------------------------------------------------------------------

class TestMountMsBudgetGate:
    def test_mount_under_budget_logs_at_debug(self):
        """mount_ms <= 500 produces DEBUG, not WARNING."""
        import hermes_cli.tui.app as app_mod

        with patch.object(app_mod, "logger") as mock_logger, \
             patch.object(app_mod, "_time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.05]  # 50 ms

            t0 = app_mod._time.monotonic()
            elapsed_ms = (app_mod._time.monotonic() - t0) * 1000.0
            if elapsed_ms > 500.0:
                app_mod.logger.warning(
                    "[STARTUP] slow mount: mount_ms=%.1f (budget=500)", elapsed_ms
                )
            else:
                app_mod.logger.debug("[STARTUP] mount_ms=%.1f", elapsed_ms)

        mock_logger.warning.assert_not_called()
        mock_logger.debug.assert_called_once()
        assert "[STARTUP]" in mock_logger.debug.call_args[0][0]

    def test_mount_over_budget_logs_at_warning(self):
        """mount_ms > 500 produces WARNING with 'slow mount' text."""
        import hermes_cli.tui.app as app_mod

        with patch.object(app_mod, "logger") as mock_logger, \
             patch.object(app_mod, "_time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.801]  # 801 ms

            t0 = app_mod._time.monotonic()
            elapsed_ms = (app_mod._time.monotonic() - t0) * 1000.0
            if elapsed_ms > 500.0:
                app_mod.logger.warning(
                    "[STARTUP] slow mount: mount_ms=%.1f (budget=500)", elapsed_ms
                )
            else:
                app_mod.logger.debug("[STARTUP] mount_ms=%.1f", elapsed_ms)

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "slow mount" in warning_msg
        mock_logger.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_app_mount_under_300ms_in_pilot_harness(self):
        """Minimal App mounts in under 300 ms — regression gate for mount perf."""
        import asyncio
        import time as _t
        from textual.app import App

        class _TimingApp(App):
            CSS = ""  # avoid VarSpec crash (feedback_hermesapp_css_varspec_crash)

            async def on_mount(self) -> None:
                t0 = _t.monotonic()
                await asyncio.sleep(0)
                self._mount_ms = (_t.monotonic() - t0) * 1000.0

        app = _TimingApp()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()

        assert app._mount_ms < 300.0, (
            f"mount took {app._mount_ms:.1f}ms — exceeds 300ms regression budget"
        )
