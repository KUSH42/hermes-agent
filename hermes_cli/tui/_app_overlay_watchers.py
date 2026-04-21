"""_OverlayWatchersMixin — reactive watchers for approval/clarify/undo overlays."""
from __future__ import annotations

from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState, UndoOverlayState


class _OverlayWatchersMixin:
    """Reactive watchers for overlay state (approval, clarify, sudo, secret, undo).

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def watch_clarify_state(self, value: "ChoiceOverlayState | None") -> None:
        from hermes_cli.tui.widgets import ClarifyWidget
        try:
            w = self.query_one(ClarifyWidget)  # type: ignore[attr-defined]
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()  # type: ignore[attr-defined]
                self._dismiss_floating_panels()  # type: ignore[attr-defined]
                self.call_after_refresh(w.focus)  # type: ignore[attr-defined]
            else:
                if not self.agent_running and not self.command_running:  # type: ignore[attr-defined]
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)  # type: ignore[attr-defined]
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())  # type: ignore[attr-defined]

    def watch_approval_state(self, value: "ChoiceOverlayState | None") -> None:
        from hermes_cli.tui.widgets import ApprovalWidget
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            self.query_one(DrawilleOverlay).signal("waiting" if value is not None else "thinking")  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            w = self.query_one(ApprovalWidget)  # type: ignore[attr-defined]
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._hide_completion_overlay_if_present()  # type: ignore[attr-defined]
                self._dismiss_floating_panels()  # type: ignore[attr-defined]
                self.call_after_refresh(w.focus)  # type: ignore[attr-defined]
            else:
                if not self.agent_running and not self.command_running:  # type: ignore[attr-defined]
                    try:
                        self.call_after_refresh(self.query_one("#input-area").focus)  # type: ignore[attr-defined]
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())  # type: ignore[attr-defined]

    def watch_highlighted_candidate(self, c: Any) -> None:
        """Route highlighted candidate to PreviewPanel (PathCandidate only)."""
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel as _PP
            from hermes_cli.tui.path_search import PathCandidate as _PC
            panel = self.query_one(_PP)  # type: ignore[attr-defined]
            panel.candidate = c if isinstance(c, _PC) else None
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            comp = self.query_one(_CO)  # type: ignore[attr-defined]
            if c is None:
                comp.add_class("--no-preview")
            else:
                comp.remove_class("--no-preview")
        except NoMatches:
            pass

    def watch_sudo_state(self, value: "SecretOverlayState | None") -> None:
        from hermes_cli.tui.widgets import SudoWidget
        try:
            w = self.query_one(SudoWidget)  # type: ignore[attr-defined]
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()  # type: ignore[attr-defined]
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())  # type: ignore[attr-defined]

    def watch_secret_state(self, value: "SecretOverlayState | None") -> None:
        from hermes_cli.tui.widgets import SecretWidget
        try:
            w = self.query_one(SecretWidget)  # type: ignore[attr-defined]
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()  # type: ignore[attr-defined]
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())  # type: ignore[attr-defined]

    def watch_status_error(self, value: str) -> None:
        """Update TitledRule error state and hint phase when error changes."""
        from hermes_cli.tui.widgets import TitledRule
        try:
            self.query_one("#input-rule", TitledRule).set_error(bool(value))  # type: ignore[attr-defined]
        except NoMatches:
            pass
        self._set_hint_phase(self._compute_hint_phase())  # type: ignore[attr-defined]
        _timer = getattr(self, "_status_error_timer", None)
        if _timer is not None:
            try:
                _timer.stop()
            except Exception:
                pass
            self._status_error_timer = None  # type: ignore[attr-defined]
        if value:
            self._status_error_timer = self.set_timer(  # type: ignore[attr-defined]
                10.0, lambda v=value: self._auto_clear_status_error(v)
            )

    def _auto_clear_status_error(self, expected: str) -> None:
        """Clear status_error if it still matches *expected*."""
        self._status_error_timer = None  # type: ignore[attr-defined]
        if self.status_error == expected:  # type: ignore[attr-defined]
            self.status_error = ""  # type: ignore[attr-defined]

    def watch_undo_state(self, value: "UndoOverlayState | None") -> None:
        from hermes_cli.tui.widgets import ApprovalWidget, ClarifyWidget, SecretWidget, SudoWidget, UndoConfirmOverlay
        try:
            w = self.query_one(UndoConfirmOverlay)  # type: ignore[attr-defined]
            w.display = value is not None
            if value is not None:
                w.update(value)
                self._dismiss_floating_panels()  # type: ignore[attr-defined]
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)  # type: ignore[attr-defined]
                        if aw.display:
                            aw.pause_countdown()
                    except NoMatches:
                        pass
            else:
                for widget_type in (ApprovalWidget, ClarifyWidget, SudoWidget, SecretWidget):
                    try:
                        aw = self.query_one(widget_type)  # type: ignore[attr-defined]
                        if aw.display and getattr(aw, "_was_paused", False):
                            aw.resume_countdown()
                    except NoMatches:
                        pass
        except NoMatches:
            pass
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
            if value is not None:
                inp.disabled = True
            elif not self.agent_running and not self.command_running:  # type: ignore[attr-defined]
                inp.disabled = False
        except NoMatches:
            pass
        if value is None:
            self._pending_undo_panel = None  # type: ignore[attr-defined]
