"""ModalOverlayMixin — shared focus-stack and CSS-class discipline for all overlays.

Every overlay that uses --modal must inherit this mixin. It owns:
  - Capturing the focus caller on mount
  - push_modal / pop_modal bookkeeping on HermesApp
  - Esc binding (action_dismiss_modal → dismiss_overlay)
  - Focus restoration on unmount

Permanent widgets (InterruptOverlay, ReferenceModal, ContextMenu) override
dismiss_overlay() to hide themselves without removal. Ephemeral widgets
(SkillPickerOverlay) use the default which calls self.remove().
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.widget import Widget

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class ModalOverlayMixin:
    """Mixin for overlay widgets that participate in the modal focus-arbiter.

    Usage
    -----
    Inherit alongside Widget (or Screen):

        class MyOverlay(ModalOverlayMixin, Widget):
            ...

    The mixin calls ``self.app.push_modal`` / ``self.app.pop_modal`` if
    HermesApp has those methods; gracefully degrades otherwise.

    Subclasses that are *permanent* (never removed from DOM) MUST override
    ``dismiss_overlay()`` to hide themselves and call
    ``self.app.pop_modal(self)`` manually after restoring focus.

    Subclasses that are *ephemeral* (removed on dismiss) can rely on the
    default ``dismiss_overlay()`` which calls ``self.remove()``.
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "close", priority=True, show=False),
    ]

    _focus_caller: Widget | None = None

    # ------------------------------------------------------------------
    # Focus capture helper (callable before on_mount too)
    # ------------------------------------------------------------------

    def _capture_focus_caller(self) -> None:
        """Record the widget that currently holds focus before we steal it."""
        try:
            focused = self.app.focused  # type: ignore[attr-defined]
            self._focus_caller = focused
        except Exception:
            # app not yet attached or no focused widget — safe to ignore
            _log.debug("ModalOverlayMixin._capture_focus_caller: could not read app.focused", exc_info=True)

    # ------------------------------------------------------------------
    # Textual lifecycle hooks
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Capture caller, register in stack, mark CSS."""
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # type: ignore[attr-defined]
        except AttributeError:
            _log.debug("ModalOverlayMixin.on_mount: app has no push_modal (HermesApp not yet patched)")
        self.add_class("--modal")  # il-m1: owned by ModalOverlayMixin; do not set raw --modal elsewhere

    def on_unmount(self) -> None:
        """Restore focus, remove CSS class, deregister from stack."""
        target = self._restore_focus_to()
        self.remove_class("--modal")  # il-m1: owned by ModalOverlayMixin
        try:
            self.app.pop_modal(self)  # type: ignore[attr-defined]
        except AttributeError:
            _log.debug("ModalOverlayMixin.on_unmount: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("ModalOverlayMixin.on_unmount: focus() on target failed", exc_info=True)

    # ------------------------------------------------------------------
    # Focus restoration
    # ------------------------------------------------------------------

    def _restore_focus_to(self) -> Widget | None:
        """Return the widget to focus after this overlay closes.

        Priority:
          1. _focus_caller if still mounted
          2. HermesInput if found in app DOM
          3. None (caller decides)
        """
        caller = self._focus_caller
        if caller is not None:
            try:
                if caller.is_mounted:
                    return caller
            except Exception:
                pass  # is_mounted check failed — treat as unmounted
        # Fallback: try HermesInput
        try:
            from hermes_cli.tui.input_widget import HermesInput  # local import to avoid circular
            return self.app.query_one(HermesInput)  # type: ignore[attr-defined]
        except Exception:
            # NoMatches or ImportError — expected if HermesInput not in DOM
            return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_dismiss_modal(self) -> None:
        """Esc binding: delegate to dismiss_overlay."""
        self.dismiss_overlay()

    # ------------------------------------------------------------------
    # Override point
    # ------------------------------------------------------------------

    def dismiss_overlay(self) -> None:
        """Close the overlay.

        Default (ephemeral): calls self.remove(). on_unmount fires → stack pop + focus restore.
        Permanent widgets override: hide themselves, call app.pop_modal, restore focus directly.
        """
        try:
            self.remove()  # type: ignore[attr-defined]
        except Exception:
            _log.debug("ModalOverlayMixin.dismiss_overlay: remove() failed", exc_info=True)
