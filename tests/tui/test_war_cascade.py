"""WAR-1..WAR-5: watch_agent_running cascade reduction tests.

Spec: /home/xush/.hermes/spec_war_agent_running_cascade.md
12 tests, no DOM required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch
from textual.css.query import NoMatches

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_app(**overrides) -> MagicMock:
    """Minimal mock satisfying watch_agent_running's attribute contract."""
    app = MagicMock()
    app.status_phase = None
    app._svc_spinner = MagicMock()
    app._svc_commands = MagicMock()
    app.hooks = MagicMock()
    app.hooks.fire = MagicMock()
    app.query_one.side_effect = NoMatches()
    app.call_after_refresh = MagicMock()
    app.browse_mode = False
    app.undo_state = None
    app._last_user_input = ""
    app.feedback = MagicMock()
    app._sync_workspace_polling_state = MagicMock()
    app._svc_browse = MagicMock()
    app._interrupt_source = None
    app.status_error = ""
    app._anim_force = None
    for k, v in overrides.items():
        setattr(app, k, v)
    return app


def _run_war(app: MagicMock, value: bool) -> None:
    """Call watch_agent_running(value) as unbound method on mock app."""
    from hermes_cli.tui.app import HermesApp
    HermesApp.watch_agent_running(app, value)


def _make_spinner_svc(app: MagicMock | None = None):
    """Build a SpinnerService backed by a mock app."""
    from hermes_cli.tui.services.spinner import SpinnerService
    mock_app = app or MagicMock()
    svc = SpinnerService.__new__(SpinnerService)
    svc.app = mock_app
    return svc, mock_app


# ── WAR-1: duplicate signal("complete") removed ────────────────────────────────

class TestWAR1NoDuplicateComplete:

    def test_war1_signal_complete_fires_once(self):
        """signal("complete") must fire exactly once on agent stop."""
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
        overlay = MagicMock()
        overlay.signal = MagicMock()

        app = _make_app()

        def _qo(cls, *args, **kwargs):
            if cls is DrawbrailleOverlay or (isinstance(cls, type) and issubclass(cls, DrawbrailleOverlay)):
                return overlay
            raise NoMatches()

        app.query_one.side_effect = _qo

        _run_war(app, False)

        complete_calls = [c for c in overlay.signal.call_args_list if c == call("complete")]
        assert overlay.signal.call_count >= 1, "signal() never called"
        assert len(complete_calls) == 1, (
            f"signal('complete') called {len(complete_calls)} times, expected 1; "
            f"all calls: {overlay.signal.call_args_list}"
        )


# ── WAR-2: OutputPanel queried once per branch ─────────────────────────────────

class TestWAR2OutputPanelQueriedOnce:

    def _count_output_panel_queries(self, app: MagicMock) -> int:
        from hermes_cli.tui.widgets import OutputPanel
        return sum(
            1 for c in app.query_one.call_args_list
            if c.args and c.args[0] is OutputPanel
        )

    def test_war2_output_panel_queried_once_on_start(self):
        from hermes_cli.tui.widgets import OutputPanel
        output = MagicMock()
        output.current_message = None
        output.new_message = MagicMock(return_value=None)
        output.reset_turn_capture = MagicMock()
        output.query_one.side_effect = NoMatches()

        app = _make_app()
        app.query_one.side_effect = lambda cls, *a, **kw: (
            output if cls is OutputPanel else (_ for _ in ()).throw(NoMatches())
        )

        _run_war(app, True)

        count = self._count_output_panel_queries(app)
        assert count == 1, f"query_one(OutputPanel) called {count} times on True, expected 1"

    def test_war2_output_panel_queried_once_on_stop(self):
        from hermes_cli.tui.widgets import OutputPanel
        output = MagicMock()
        output.flush_live = MagicMock()
        output.evict_old_turns = MagicMock()

        app = _make_app()

        def _qo(cls, *a, **kw):
            if cls is OutputPanel:
                return output
            raise NoMatches()

        app.query_one.side_effect = _qo

        _run_war(app, False)

        count = self._count_output_panel_queries(app)
        assert count == 1, f"query_one(OutputPanel) called {count} times on False, expected 1"

    def test_war2_new_message_called_when_output_available(self):
        """new_message() runs even when the inner ThinkingWidget query fails."""
        from hermes_cli.tui.widgets import OutputPanel
        output = MagicMock()
        output.reset_turn_capture = MagicMock()
        output.current_message = None
        new_msg = MagicMock()
        output.new_message = MagicMock(return_value=new_msg)
        # ThinkingWidget query inside reset_turn_capture block raises NoMatches
        output.query_one.side_effect = NoMatches()

        app = _make_app()
        app.query_one.side_effect = lambda cls, *a, **kw: (
            output if cls is OutputPanel else (_ for _ in ()).throw(NoMatches())
        )

        _run_war(app, True)

        output.new_message.assert_called_once()


# ── WAR-3: deferred turn-end operations ───────────────────────────────────────

class TestWAR3DeferredTurnEnd:

    def test_war3_evict_deferred(self):
        """evict_old_turns must not be called synchronously; must be deferred."""
        from hermes_cli.tui.widgets import OutputPanel
        output = MagicMock()
        output.flush_live = MagicMock()
        output.evict_old_turns = MagicMock()

        app = _make_app()
        app.query_one.side_effect = lambda cls, *a, **kw: (
            output if cls is OutputPanel else (_ for _ in ()).throw(NoMatches())
        )

        _run_war(app, False)

        output.evict_old_turns.assert_not_called()
        app.call_after_refresh.assert_any_call(output.evict_old_turns)

    def test_war3_browse_anchors_deferred(self):
        """rebuild_browse_anchors must be deferred when browse_mode=True."""
        app = _make_app(browse_mode=True)

        _run_war(app, False)

        app._svc_browse.rebuild_browse_anchors.assert_not_called()
        app.call_after_refresh.assert_any_call(app._svc_browse.rebuild_browse_anchors)

    def test_war3_turn_completed_deferred(self):
        """HistorySearchOverlay.TurnCompleted must be posted via call_after_refresh."""
        from hermes_cli.tui.widgets.overlays import HistorySearchOverlay

        hs = MagicMock(spec=HistorySearchOverlay)
        hs.has_class = MagicMock(return_value=True)

        app = _make_app()

        def _qo(cls, *a, **kw):
            if cls is HistorySearchOverlay:
                return hs
            raise NoMatches()

        app.query_one.side_effect = _qo

        _run_war(app, False)

        # post_message must NOT be called synchronously
        hs.post_message.assert_not_called()
        # call_after_refresh must have been scheduled
        assert app.call_after_refresh.called, "call_after_refresh not scheduled for TurnCompleted"


# ── WAR-4: _sync_workspace_polling_state not called directly on True ───────────

class TestWAR4SyncWorkspaceNoDuplicate:

    def test_war4_sync_workspace_not_direct_on_start(self):
        """_sync_workspace_polling_state must NOT be called directly in the True branch.

        (It fires via the hook chain; verifying absence of direct call proves WAR-4 is fixed.)
        """
        app = _make_app()
        # Swallow the hook chain so only direct calls register
        app.hooks.fire = MagicMock()

        _run_war(app, True)

        app._sync_workspace_polling_state.assert_not_called()

    def test_war4_sync_workspace_once_on_stop(self):
        """_sync_workspace_polling_state called exactly once in the False branch."""
        app = _make_app()

        _run_war(app, False)

        assert app._sync_workspace_polling_state.call_count == 1, (
            f"Expected 1 call on False, got {app._sync_workspace_polling_state.call_count}"
        )


# ── WAR-5: signal("thinking") routed through drawbraille_show_hide ────────────

class TestWAR5ThinkingSignalViaShowHide:

    def test_war5_thinking_signal_via_show_hide(self):
        """signal('thinking') fires via drawbraille_show_hide — query_one called once."""
        overlay = MagicMock()
        overlay.signal = MagicMock()

        mock_app = MagicMock()
        mock_app._anim_force = None
        mock_app.query_one.return_value = overlay

        svc, _ = _make_spinner_svc(mock_app)

        # Patch _overlay_config where it is defined (imported inside the function)
        with patch("hermes_cli.tui.drawbraille_overlay._overlay_config") as mock_cfg:
            cfg = MagicMock()
            cfg.trigger = "agent_running"
            cfg.dim_background = False
            mock_cfg.return_value = cfg

            svc.drawbraille_show_hide(True, signal_on_show="thinking")

        overlay.signal.assert_called_once_with("thinking")
        # query_one called once for the overlay (not again for the signal)
        assert mock_app.query_one.call_count == 1, (
            f"query_one called {mock_app.query_one.call_count} times, expected 1"
        )

    def test_war5_no_signal_on_hide(self):
        """No signal fired when running=False."""
        overlay = MagicMock()
        overlay.signal = MagicMock()

        mock_app = MagicMock()
        mock_app._anim_force = None
        mock_app.query_one.return_value = overlay

        svc, _ = _make_spinner_svc(mock_app)

        with patch("hermes_cli.tui.drawbraille_overlay._overlay_config") as mock_cfg:
            cfg = MagicMock()
            cfg.trigger = "agent_running"
            cfg.dim_background = False
            mock_cfg.return_value = cfg

            svc.drawbraille_show_hide(False, signal_on_show=None)

        overlay.signal.assert_not_called()

    def test_war5_force_on_path_carries_signal(self):
        """signal fired on the force-on early-return path."""
        overlay = MagicMock()
        overlay.signal = MagicMock()

        mock_app = MagicMock()
        mock_app._anim_force = "on"
        mock_app.query_one.return_value = overlay

        svc, _ = _make_spinner_svc(mock_app)

        with patch("hermes_cli.tui.drawbraille_overlay._overlay_config") as mock_cfg:
            cfg = MagicMock()
            mock_cfg.return_value = cfg

            svc.drawbraille_show_hide(True, signal_on_show="thinking")

        overlay.signal.assert_called_once_with("thinking")
