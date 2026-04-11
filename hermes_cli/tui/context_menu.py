"""Context menu widget for the Hermes TUI.

Right-clicking on interactive TUI elements shows a context-sensitive
floating menu. The menu is position-clamped to stay within viewport
bounds and dismisses on blur, Escape, or item click.

``ContextMenu.can_focus = True`` is required so that ``on_blur`` fires
when the user clicks elsewhere, enabling automatic dismissal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual.app import ComposeResult
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
    """

    def __init__(self, item: MenuItem, **kwargs) -> None:
        super().__init__(**kwargs)
        self._item = item

    def on_mount(self) -> None:
        label = self._item.label
        shortcut = self._item.shortcut
        if shortcut:
            self.update(f"{label}  [dim]{shortcut}[/dim]")
        else:
            self.update(label)

    def on_click(self) -> None:
        try:
            self._item.action()
        except Exception:
            pass
        try:
            self.app.query_one(ContextMenu).dismiss()
        except NoMatches:
            pass


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
        border: tall $primary;
        padding: 0 1;
    }
    ContextMenu.--visible { display: block; }
    """

    def show(self, items: list[MenuItem], screen_x: int, screen_y: int) -> None:
        """Position and reveal the context menu with the given items.

        Removes any existing children, mounts fresh ``_ContextItem`` and
        ``_ContextSep`` widgets, clamps coordinates to viewport, sets
        ``styles.offset``, adds ``--visible``, and calls ``self.focus()``
        to arm ``on_blur`` dismissal.
        """
        if not items:
            return

        # Tear down previous contents (if menu was already visible)
        for child in list(self.children):
            child.remove()

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

        # Build widget list
        new_widgets: list[Widget] = []
        for item in items:
            if item.separator_above:
                new_widgets.append(_ContextSep())
            new_widgets.append(_ContextItem(item))

        if new_widgets:
            self.mount(*new_widgets)

        self.add_class("--visible")
        self.focus()

    def dismiss(self) -> None:
        """Hide the context menu (idempotent)."""
        self.remove_class("--visible")

    def on_blur(self) -> None:
        """Dismiss when focus leaves the menu."""
        self.dismiss()

    def on_key(self, event) -> None:
        """Escape dismisses the menu and consumes the event."""
        if event.key == "escape":
            self.dismiss()
            event.prevent_default()
