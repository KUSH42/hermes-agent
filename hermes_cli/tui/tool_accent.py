"""ToolAccent — single-source vertical gutter rail for ToolPanel.

Replaces v2 border-left AND inline ┊ from ToolHeader.render().
State drives background color; position drives join chars via render_line.

States:   pending | streaming | ok | error | warning | muted
Position: solo | first | mid | last  (controls ┬/├/╰ join chars)

Architecture: tui-tool-panel-v3-spec.md §5.1
"""
from __future__ import annotations

from typing import ClassVar, Literal

from rich.segment import Segment
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget


class ToolAccent(Widget):
    COMPONENT_CLASSES: ClassVar[set[str]] = {"tool-accent--rail"}
    DEFAULT_CSS = """
    ToolAccent {
        width: 1;
        background: $primary 15%;
    }
    """

    state: reactive[str] = reactive("pending")
    _position: str = "solo"

    def watch_state(self, old: str, new: str) -> None:
        if old:
            self.remove_class(f"-{old}")
        self.add_class(f"-{new}")

    def set_position(self, position: Literal["solo", "first", "mid", "last"]) -> None:
        self._position = position
        self.refresh()

    def render_line(self, y: int) -> Strip:
        h = self.size.height
        char = "┃"
        pos = self._position
        if pos == "first" and y == 0:
            char = "┬"
        elif pos == "mid" and y == 0:
            char = "├"
        elif pos == "last" and y == h - 1:
            char = "╰"
        style = self.rich_style
        return Strip([Segment(char, style)])
