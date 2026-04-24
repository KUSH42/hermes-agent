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
from typing import Callable

logger = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static


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
            self.app.query_one(ContextMenu).remove_class("--visible")
        except NoMatches:
            pass
        if prev is not None and prev.is_attached:
            prev.focus()
        else:
            try:
                self.app.query_one("#input-area").focus()
            except Exception:
                logger.debug("ContextMenu: focus restore to #input-area failed", exc_info=True)


class ContextMenu(Widget):
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
        self.add_class("--visible")
        self.focus()

    def dismiss(self) -> None:
        """Hide the context menu (idempotent).

        Explicitly returns focus to ``#input-area`` when the menu had focus,
        so that mouse-scroll events reach the OutputPanel rather than being
        swallowed by a hidden but still-focused ContextMenu widget.
        """
        self.remove_class("--visible")
        if self.app.focused is self:
            try:
                self.app.query_one("#input-area").focus()
            except Exception:
                logger.debug("ContextMenu.action_dismiss: focus restore to #input-area failed", exc_info=True)

    def on_blur(self) -> None:
        """Dismiss when focus leaves the menu."""
        self.dismiss()

    def on_key(self, event) -> None:
        """Escape dismisses the menu and consumes the event."""
        if event.key == "escape":
            self.dismiss()
            event.prevent_default()
