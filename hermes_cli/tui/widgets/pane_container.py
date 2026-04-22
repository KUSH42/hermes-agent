"""
PaneContainer — the visual shell for a layout pane.
Hosts one content widget; handles border, title, and focus ring.
"""
from __future__ import annotations
from textual.widget import Widget
from textual.app import ComposeResult
from hermes_cli.tui.pane_manager import PaneId


class PaneContainer(Widget):
    """
    A resizable pane shell. Content is mounted dynamically after compose.
    """

    DEFAULT_CSS = """
    PaneContainer {
        border: round #333333;
    }
    PaneContainer:focus-within {
        border: round #5f87d7;
    }
    """

    def __init__(self, pane_id: PaneId, **kwargs) -> None:
        super().__init__(**kwargs)
        self._pane_id = pane_id

    def compose(self) -> ComposeResult:
        return
        yield  # noqa: unreachable — needed to satisfy ComposeResult type

    def set_content(self, widget: Widget) -> None:
        """Mount a content widget into this pane."""
        self.mount(widget)
