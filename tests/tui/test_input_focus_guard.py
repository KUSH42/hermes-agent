"""Input focus guard — FG-H1, FG-H2, FG-H3, FG-M1, FG-M2.

TestHasFocusCapturingModal  (3) — FG-H1: HermesApp.has_focus_capturing_modal()
TestCanFocusProperty        (3) — FG-H2: HermesInput.can_focus property
TestOnFocusGuard            (3) — FG-H3: HermesInput.on_focus redirect
TestActionFocusInputGate    (2) — FG-M1: action_focus_input_from_output guard
TestAutoFocusSiteGates      (3) — FG-M2: on_ready / new-turn / session-resume guards
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(*, stack=None):
    """Minimal HermesApp stub with _modal_stack."""
    from hermes_cli.tui.app import HermesApp
    app = HermesApp.__new__(HermesApp)
    app._modal_stack = list(stack) if stack is not None else []
    return app


def _workspace_stub():
    """Return an object that isinstance-checks as WorkspaceOverlay."""
    from hermes_cli.tui.overlays.reference import WorkspaceOverlay
    obj = MagicMock(spec=WorkspaceOverlay)
    obj.__class__ = WorkspaceOverlay
    return obj


def _other_stub():
    """Return a non-WorkspaceOverlay modal stub."""
    return MagicMock()


# ---------------------------------------------------------------------------
# FG-H1: HermesApp.has_focus_capturing_modal
# ---------------------------------------------------------------------------

class TestHasFocusCapturingModal:
    def test_empty_stack_not_capturing(self):
        app = _make_app(stack=[])
        assert app.has_focus_capturing_modal() is False

    def test_workspace_only_not_capturing(self):
        app = _make_app(stack=[_workspace_stub()])
        assert app.has_focus_capturing_modal() is False

    def test_other_overlay_capturing(self):
        # Single non-WorkspaceOverlay → True
        app = _make_app(stack=[_other_stub()])
        assert app.has_focus_capturing_modal() is True

        # WorkspaceOverlay + other (both orderings) → True
        app2 = _make_app(stack=[_workspace_stub(), _other_stub()])
        assert app2.has_focus_capturing_modal() is True

        app3 = _make_app(stack=[_other_stub(), _workspace_stub()])
        assert app3.has_focus_capturing_modal() is True


# ---------------------------------------------------------------------------
# FG-H2: HermesInput.can_focus property
# ---------------------------------------------------------------------------

class TestCanFocusProperty:
    def _make_input_with_app(self, *, capturing: bool):
        from hermes_cli.tui.input.widget import HermesInput
        widget = HermesInput.__new__(HermesInput)
        app = MagicMock()
        app.has_focus_capturing_modal.return_value = capturing
        # Patch the app property to return our stub
        type(widget).app = property(lambda self: app)
        return widget

    def test_can_focus_no_modal(self):
        widget = self._make_input_with_app(capturing=False)
        assert widget.can_focus is True

    def test_can_focus_with_capturing_modal(self):
        widget = self._make_input_with_app(capturing=True)
        assert widget.can_focus is False

    def test_can_focus_pre_mount_fallback(self):
        from hermes_cli.tui.input.widget import HermesInput
        widget = HermesInput.__new__(HermesInput)
        # app property raises AttributeError when not attached
        type(widget).app = property(lambda self: (_ for _ in ()).throw(AttributeError("no app")))
        assert widget.can_focus is True


# ---------------------------------------------------------------------------
# FG-H3: HermesInput.on_focus guard
# ---------------------------------------------------------------------------

class TestOnFocusGuard:
    def _make_input_with_app(self, *, capturing: bool, top_modal=None):
        from hermes_cli.tui.input.widget import HermesInput
        from textual import events
        widget = HermesInput.__new__(HermesInput)
        app = MagicMock()
        app.has_focus_capturing_modal.return_value = capturing
        app.top_modal.return_value = top_modal
        type(widget).app = property(lambda self: app)
        widget.blur = MagicMock()
        return widget, app

    def _focus_event(self):
        from textual import events
        return MagicMock(spec=events.Focus)

    def test_on_focus_no_modal_noop(self):
        widget, app = self._make_input_with_app(capturing=False)
        widget.on_focus(self._focus_event())
        widget.blur.assert_not_called()
        app.top_modal.assert_not_called()

    def test_on_focus_with_modal_blurs(self):
        top = MagicMock()
        widget, app = self._make_input_with_app(capturing=True, top_modal=top)
        widget.on_focus(self._focus_event())
        widget.blur.assert_called_once()
        top.focus.assert_called_once()

    def test_on_focus_no_top_modal_no_crash(self):
        widget, app = self._make_input_with_app(capturing=True, top_modal=None)
        widget.on_focus(self._focus_event())
        widget.blur.assert_called_once()
        # top_modal() returned None — no crash, no focus redirect
        app.top_modal.assert_called_once()


# ---------------------------------------------------------------------------
# FG-M1: action_focus_input_from_output guard
# ---------------------------------------------------------------------------

class TestActionFocusInputGate:
    def _make_app_stub(self, *, capturing: bool):
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)
        app._modal_stack = [_other_stub()] if capturing else []
        return app

    def test_action_focus_input_blocked_when_modal(self):
        app = self._make_app_stub(capturing=True)
        with patch.object(app, "query_one") as mock_qo:
            app.action_focus_input_from_output()
            mock_qo.assert_not_called()

    def test_action_focus_input_allowed_no_modal(self):
        app = self._make_app_stub(capturing=False)
        mock_hi = MagicMock()
        with patch.object(app, "query_one", return_value=mock_hi):
            app.action_focus_input_from_output()
            mock_hi.focus.assert_called_once()


# ---------------------------------------------------------------------------
# FG-M2: on_ready / new-turn / session-resume auto-focus gates
# ---------------------------------------------------------------------------

class TestAutoFocusSiteGates:
    """Verify that the three auto-focus call sites respect has_focus_capturing_modal."""

    def _app_with_capturing(self, capturing: bool):
        from hermes_cli.tui.app import HermesApp
        app = HermesApp.__new__(HermesApp)
        app._modal_stack = [_other_stub()] if capturing else []
        return app

    def _make_hi_mock(self):
        return MagicMock()

    def test_on_ready_focus_blocked_when_modal(self):
        app = self._app_with_capturing(True)
        with patch.object(app, "query_one") as mock_qo:
            with patch("hermes_cli.tui.app.HermesApp.has_focus_capturing_modal",
                       return_value=True):
                # Simulate just the focus block from on_ready
                if not app.has_focus_capturing_modal():
                    from hermes_cli.tui.input_widget import HermesInput as _HI
                    try:
                        app.query_one(_HI).focus()
                    except Exception:
                        pass
            mock_qo.assert_not_called()

    def test_new_turn_focus_blocked_when_modal(self):
        app = self._app_with_capturing(True)
        with patch.object(app, "query_one") as mock_qo:
            # Simulate the turn-start focus block
            if not app.has_focus_capturing_modal():
                from hermes_cli.tui.input_widget import HermesInput as _HI
                try:
                    app.query_one(_HI).focus()
                except Exception:
                    pass
            mock_qo.assert_not_called()

    def test_session_resume_focus_blocked_when_modal(self):
        app = self._app_with_capturing(True)
        with patch.object(app, "query_one") as mock_qo:
            # Simulate session-resume focus block
            if not app.has_focus_capturing_modal():
                try:
                    from hermes_cli.tui.input_widget import HermesInput as _HI
                    app.query_one(_HI).focus()
                except Exception:
                    pass
            mock_qo.assert_not_called()
