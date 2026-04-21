"""TUI message types for inter-widget communication.

Phase D: ToolRerunRequested, PathClicked.
"""
from __future__ import annotations

from textual.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.tool_panel import ToolPanel


class ToolRerunRequested(Message):
    """Posted when the user presses 'r' on a ToolPanel to request re-run."""

    def __init__(self, panel: "ToolPanel") -> None:
        super().__init__()
        self.panel = panel


class PathClicked(Message):
    """Posted when the user clicks on a path token in a tool output."""

    def __init__(self, path: str, absolute: bool = False) -> None:
        super().__init__()
        self.path = path
        self.absolute = absolute
