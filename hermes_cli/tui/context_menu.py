"""Context menu widget for the Hermes TUI.

Right-clicking on interactive TUI elements shows a context-sensitive
floating menu. The menu is position-clamped to stay within viewport
bounds and dismisses on blur, Escape, or item click.

``ContextMenu.can_focus = True`` is required so that ``on_blur`` fires
when the user clicks elsewhere, enabling automatic dismissal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin


@dataclass
class MenuItem:
    """A single entry in the context menu.

    ``separator_above=True`` causes a ``_ContextSep`` row to be inserted
    immediately before this item when the menu is built.
    """

    label: str                      # Rich markup supported
    shortcut: str                   # dim right-aligned hint
    action: Callable[[], None]
    separator_above: bool = False   # insert visual separator above this item


class _ContextSep(Static):
    """Visual separator row inside a ContextMenu."""

    DEFAULT_CSS = """
    _ContextSep {
        height: 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("──────────────────────", **kwargs)


class _ContextItem(Static):
    """A single clickable menu item."""

    DEFAULT_CSS = """
    _ContextItem {
        height: 1;
    }
    _ContextItem.--selected {
        background: $accent 25%;
    }
    """

    def __init__(self, item: MenuItem, **kwargs) -> None:
        # Pass content at construction so it renders on first paint without
        # waiting for on_mount, which fires asynchronously as a message.
        label = item.label
        shortcut = item.shortcut
        text = f"{label}  [dim]{shortcut}[/dim]" if shortcut else label
        super().__init__(text, **kwargs)
        self._item = item

    def on_click(self) -> None:
        try:
            menu = self.app.query_one(ContextMenu)
            prev = menu._prev_focus
        except (NoMatches, AttributeError):
            prev = None
        try:
            self._item.action()
        except Exception:
            logger.exception("ContextMenu: item action %r raised", self._item.label)
            try:
                self.app.notify(f"Action failed: {self._item.label}", severity="error", timeout=4)
            except Exception:
                logger.debug("ContextMenu: app.notify failed during action error report", exc_info=True)
        try:
            self.app.query_one(ContextMenu).dismiss()
        except NoMatches:
            pass


class ContextMenu(ModalOverlayMixin, Widget):
    """Floating context menu widget.

    Positioned absolutely at arbitrary screen coordinates via
    ``position: absolute`` CSS (see ``DEFAULT_CSS``). Rendered on the
    ``overlay`` layer so it floats above all default-layer widgets.

    Lifecycle
    ---------
    - ``show(items, screen_x, screen_y)`` rebuilds children, positions,
      adds ``--visible``, and calls ``self.focus()``.
    - ``dismiss()`` removes ``--visible``.
    - ``on_blur`` fires when focus leaves → calls ``dismiss()``.
    - ``on_key(escape)`` calls ``dismiss()`` and consumes the event.
    - ``_ContextItem.on_click`` calls the item action then ``dismiss()``.

    Keyboard navigation (P0-C)
    --------------------------
    Up/Down move the ``--selected`` highlight; Enter executes the selected item.
    First Down press with no selection jumps to the first non-separator item.
    """

    can_focus = True

    DEFAULT_CSS = """
    ContextMenu {
        layer: overlay;
        position: absolute;
        display: none;
        width: auto;
        height: auto;
        background: $surface;
        border: tall $primary 20%;
        padding: 0 1;
    }
    ContextMenu.--visible { display: block; }
    """

    BINDINGS = [
        Binding("up", "move_up", show=False, priority=True),
        Binding("down", "move_down", show=False, priority=True),
        Binding("enter", "execute_selected", show=False, priority=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_index: int = -1  # -1 = no selection
        self._prev_focus: Widget | None = None  # widget focused before menu opened
        self._opener_browse_target: Widget | None = None  # W-8: browse target that opened this menu

    def on_mount(self) -> None:
        # Intentionally does NOT call ModalOverlayMixin.on_mount().
        # ContextMenu is a permanent pre-mounted widget; modal registration
        # happens lazily in show(), not at DOM mount time.
        pass  # _opener_browse_target captured lazily in show() (MOD-M1)

    def on_unmount(self) -> None:
        # Intentionally does NOT call ModalOverlayMixin.on_unmount().
        # Permanent widget: never removed from DOM.
        pass

    def _items(self) -> "list[_ContextItem]":
        """Return all non-separator item widgets in display order."""
        return list(self.query(_ContextItem))

    def _apply_selection(self) -> None:
        """Update --selected class to match _selected_index."""
        items = self._items()
        for i, item in enumerate(items):
            item.set_class(i == self._selected_index, "--selected")

    def action_move_up(self) -> None:
        """Move selection up, skipping separators (P0-C)."""
        items = self._items()
        if not items:
            return
        if self._selected_index <= 0:
            self._selected_index = 0
        else:
            self._selected_index = max(0, self._selected_index - 1)
        self._apply_selection()

    def action_move_down(self) -> None:
        """Move selection down; first press jumps to item 0 (P0-C)."""
        items = self._items()
        if not items:
            return
        if self._selected_index < 0:
            self._selected_index = 0
        else:
            self._selected_index = min(len(items) - 1, self._selected_index + 1)
        self._apply_selection()

    def action_execute_selected(self) -> None:
        """Execute the highlighted item and dismiss (P0-C)."""
        items = self._items()
        if 0 <= self._selected_index < len(items):
            try:
                items[self._selected_index]._item.action()
            except Exception:
                label = items[self._selected_index]._item.label
                logger.exception("ContextMenu: execute_selected action %r raised", label)
                try:
                    self.app.notify(f"Action failed: {label}", severity="error", timeout=4)
                except Exception:
                    logger.debug("ContextMenu: app.notify failed during execute_selected error report", exc_info=True)
        self.dismiss()

    async def show(self, items: list[MenuItem], screen_x: int, screen_y: int) -> None:
        """Position and reveal the context menu with the given items.

        Removes any existing children, mounts fresh ``_ContextItem`` and
        ``_ContextSep`` widgets, clamps coordinates to viewport, sets
        ``styles.offset``, adds ``--visible``, and calls ``self.focus()``
        to arm ``on_blur`` dismissal.
        """
        if not items:
            if "--modal" in self.classes or "--visible" in self.classes:
                self.dismiss_overlay()
            return

        # Tear down previous contents (if menu was already visible); await
        # each remove so the DOM is clean before mounting new children.
        for child in list(self.children):
            await child.remove()

        # Heuristic width: max of (label length + shortcut length + padding)
        estimated_width = max(
            len(item.label) + len(item.shortcut) + 4
            for item in items
        )

        # Row count (items + separator rows)
        total_rows = len(items) + sum(1 for i in items if i.separator_above)
        menu_height = total_rows + 2  # +2 for border top/bottom

        # Clamp to viewport
        app_width = self.app.size.width
        app_height = self.app.size.height
        clamped_x = min(screen_x, max(0, app_width - estimated_width - 2))
        clamped_y = min(screen_y, max(0, app_height - menu_height - 1))

        self.styles.offset = (clamped_x, clamped_y)
        # Set explicit dimensions so the menu sizes correctly under
        # position:absolute where width/height:auto may not resolve.
        self.styles.width = estimated_width + 2  # +2 for padding 0 1
        self.styles.height = menu_height

        # Build widget list
        new_widgets: list[Widget] = []
        for item in items:
            if item.separator_above:
                new_widgets.append(_ContextSep())
            new_widgets.append(_ContextItem(item))

        if new_widgets:
            await self.mount(*new_widgets)

        self._selected_index = -1  # reset selection on each new show
        self._prev_focus = self.app.focused  # save for focus restore on item click
        # W-8 / MOD-M1: capture browse target at actual show time, not at DOM mount
        self._opener_browse_target = next(
            (w for w in self.app.query(".--browse-focused")), None
        )
        # MOD-8: use _capture_focus_caller + push_modal, then add CSS classes
        self._capture_focus_caller()  # record focus caller before stealing focus
        # Guard: if a prior show() already pushed us (re-entrant call while the async
        # body was suspended across two rapid right-clicks), pop first so we don't
        # accumulate duplicate stack entries that can never be fully dismissed.
        if "--modal" in self.classes:
            try:
                self.app.pop_modal(self)
            except AttributeError:
                pass
        try:
            self.app.push_modal(self)  # register in arbiter stack  # il-m1: push via arbiter
        except AttributeError:
            pass  # app has no push_modal — graceful degrade
        self.add_class("--modal")  # il-m1: owned by ContextMenu.show (permanent widget override)
        self.add_class("--visible")
        self.focus()

    def _restore_focus_to(self):
        """MOD-8: prefer _prev_focus over mixin default, then fall back to mixin logic."""
        pf = self._prev_focus
        if pf is not None:
            try:
                if pf.is_mounted:
                    return pf
            except Exception:
                pass  # is_mounted check failed — treat as unmounted
        return super()._restore_focus_to()

    def dismiss_overlay(self) -> None:
        """MOD-8: permanent-widget override.  Does NOT remove() self.

        MOD-M2: capture focus target first, then remove CSS, then pop stack, then focus.
        """
        target = self._restore_focus_to()  # capture before any state mutation
        # W-8 / R-2: if a browse-focused target opened this menu, restore its highlight
        if self._opener_browse_target is not None:
            try:
                self._opener_browse_target.add_class("--browse-focused")
            except Exception:
                logger.debug("ContextMenu: browse-target restore failed", exc_info=True)
        self.remove_class("--visible")
        self.remove_class("--modal")  # il-m1: owned by ContextMenu.dismiss_overlay (permanent override)
        try:
            self.app.pop_modal(self)
        except AttributeError:
            pass  # app has no pop_modal — graceful degrade
        if target is not None and self.app.focused is self:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                logger.debug("ContextMenu.dismiss_overlay: focus restore failed", exc_info=True)

    def dismiss(self) -> None:
        """Hide the context menu (idempotent). Delegates to dismiss_overlay."""
        self.dismiss_overlay()

    def on_blur(self) -> None:
        """Dismiss when focus leaves the menu."""
        self.dismiss()

    def on_key(self, event: Any) -> None:
        """Dismiss on Escape; consume so it doesn't propagate."""
        if event.key == "escape":
            event.stop()
            self.dismiss()

