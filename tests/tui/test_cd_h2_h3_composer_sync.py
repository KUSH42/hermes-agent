"""Tests for CD-H2, CD-H3, CD-M1 — composer ASSIST/MODE sync fixes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from textual.css.query import NoMatches

from hermes_cli.tui.input._assist import AssistKind
from hermes_cli.tui.input._mode import InputMode
from hermes_cli.tui.input.widget import HermesInput


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _StubInput:
    """Minimal stub for calling HermesInput methods without a live app."""

    def __init__(self, assist: AssistKind = AssistKind.NONE, mode: InputMode = InputMode.NORMAL):
        self.assist = assist
        self._mode = mode
        self.disabled = False
        self._locked = False
        self._pre_lock_disabled = False
        self.is_mounted = True
        self._rev_mode = False
        self._completion_overlay_active = False
        self.error_state = None
        self._idle_placeholder = "idle"
        self.placeholder = "idle"
        self._classes: set[str] = set()
        self.suggestion = ""
        self.app = MagicMock()

    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)

    def has_class(self, cls: str) -> bool:
        return cls in self._classes

    def set_class(self, enabled: bool, cls: str) -> None:
        if enabled:
            self.add_class(cls)
        else:
            self.remove_class(cls)

    def _refresh_placeholder(self) -> None:
        pass

    def _hide_completion_overlay(self) -> None:
        self._completion_overlay_active = False

    def _show_completion_overlay(self) -> None:
        self._completion_overlay_active = True

    def _sync_picker_chevron(self, active: bool) -> None:
        pass

    def _sync_picker_legend(self, active: bool) -> None:
        pass

    def _resolve_assist(self, target: AssistKind, suggestion: str = "") -> None:
        self.assist = target


# ---------------------------------------------------------------------------
# TestCDH2 — dismiss_completion_overlay + app.py redirect
# ---------------------------------------------------------------------------

class TestCDH2:

    def test_dismiss_completion_overlay_calls_resolve_assist(self):
        """dismiss_completion_overlay() routes through _resolve_assist when assist=OVERLAY."""
        stub = _StubInput(assist=AssistKind.OVERLAY)
        HermesInput.dismiss_completion_overlay(stub)
        assert stub.assist is AssistKind.NONE

    def test_dismiss_completion_overlay_noop_when_not_overlay(self):
        """dismiss_completion_overlay() is a no-op when assist != OVERLAY."""
        stub = _StubInput(assist=AssistKind.NONE)
        resolve_mock = MagicMock()
        stub._resolve_assist = resolve_mock
        HermesInput.dismiss_completion_overlay(stub)
        resolve_mock.assert_not_called()

    def test_hide_completion_overlay_if_present_routes_through_resolver(self):
        """_hide_completion_overlay_if_present calls dismiss_completion_overlay once."""
        from hermes_cli.tui.app import HermesApp
        mock_inp = MagicMock()
        mock_app = MagicMock(spec=HermesApp)
        mock_app.query_one.return_value = mock_inp
        HermesApp._hide_completion_overlay_if_present(mock_app)
        mock_inp.dismiss_completion_overlay.assert_called_once()

    def test_hide_completion_overlay_if_present_no_matches(self):
        """_hide_completion_overlay_if_present swallows NoMatches silently."""
        from hermes_cli.tui.app import HermesApp
        mock_app = MagicMock(spec=HermesApp)
        mock_app.query_one.side_effect = NoMatches()
        HermesApp._hide_completion_overlay_if_present(mock_app)  # must not raise


# ---------------------------------------------------------------------------
# TestCDH3 — _set_input_locked recomputes _mode
# ---------------------------------------------------------------------------

class TestCDH3:

    def test_set_input_locked_true_sets_mode_locked(self):
        """_set_input_locked(True) recomputes _mode to LOCKED immediately."""
        stub = _StubInput()
        stub._compute_mode = MagicMock(return_value=InputMode.LOCKED)
        HermesInput._set_input_locked(stub, True)
        assert stub._mode is InputMode.LOCKED

    def test_set_input_locked_false_recomputes_mode(self):
        """_set_input_locked(False) recomputes _mode after unlocking."""
        stub = _StubInput()
        stub._locked = True
        stub._compute_mode = MagicMock(return_value=InputMode.NORMAL)
        HermesInput._set_input_locked(stub, False)
        assert stub._mode is InputMode.NORMAL

    def test_set_input_locked_before_mount_is_noop(self):
        """_set_input_locked before mount leaves _mode unchanged."""
        stub = _StubInput()
        stub.is_mounted = False
        original_mode = stub._mode
        HermesInput._set_input_locked(stub, True)
        assert stub._mode is original_mode


# ---------------------------------------------------------------------------
# TestCDM1 — watch_assist recomputes _mode
# ---------------------------------------------------------------------------

class TestCDM1:

    def test_watch_assist_overlay_sets_mode_completion(self):
        """watch_assist(NONE, OVERLAY) recomputes _mode to COMPLETION."""
        stub = _StubInput()
        stub._compute_mode = MagicMock(return_value=InputMode.COMPLETION)
        HermesInput.watch_assist(stub, AssistKind.NONE, AssistKind.OVERLAY)
        assert stub._mode is InputMode.COMPLETION

    def test_watch_assist_none_sets_mode_normal(self):
        """watch_assist(OVERLAY, NONE) recomputes _mode to NORMAL."""
        stub = _StubInput(mode=InputMode.COMPLETION)
        stub._compute_mode = MagicMock(return_value=InputMode.NORMAL)
        HermesInput.watch_assist(stub, AssistKind.OVERLAY, AssistKind.NONE)
        assert stub._mode is InputMode.NORMAL

    def test_watch_assist_picker_does_not_change_mode(self):
        """watch_assist NONE->PICKER leaves mode as whatever _compute_mode returns."""
        stub = _StubInput()
        stub._compute_mode = MagicMock(return_value=InputMode.NORMAL)
        HermesInput.watch_assist(stub, AssistKind.NONE, AssistKind.PICKER)
        assert stub._mode is InputMode.NORMAL

    def test_watch_assist_mode_sync_skips_on_attr_error(self):
        """watch_assist does not propagate AttributeError from _compute_mode."""
        stub = _StubInput()
        stub._compute_mode = MagicMock(side_effect=AttributeError("not ready"))
        HermesInput.watch_assist(stub, AssistKind.NONE, AssistKind.OVERLAY)  # must not raise

    def test_composer_invariant_assist_mode_consistent(self):
        """After _resolve_assist(OVERLAY), _mode must be COMPLETION (via watch_assist)."""
        stub = _StubInput()
        # wire watch_assist to delegate to the real implementation (mode recompute)
        def _compute_mode_real(self_):
            from hermes_cli.tui.input.widget import HermesInput as _HI
            return _HI._compute_mode(self_)
        stub._compute_mode = lambda: _compute_mode_real(stub)
        # Replicate the write-site: assist = OVERLAY, then trigger watch
        stub.assist = AssistKind.OVERLAY
        stub._completion_overlay_active = True
        HermesInput.watch_assist(stub, AssistKind.NONE, AssistKind.OVERLAY)
        assert stub.assist != AssistKind.OVERLAY or stub._mode == InputMode.COMPLETION
