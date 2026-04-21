"""BrowseMinimap — 1-cell wide anchor minimap docked right inside OutputPanel.

Renders one glyph per anchor type mapped from virtual scroll position to
viewport row. Toggle with \\ while browse mode is active.
"""

from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

# Glyph per anchor type (single-width Unicode; matches _BROWSE_TYPE_GLYPH in app.py)
_TYPE_GLYPH: dict[str, str] = {
    "turn_start": "\u25b8",     # ▸
    "code_block": "\u2039",     # ‹  (first char of ‹›)
    "tool_block": "\u25a3",     # ▣
    "media":      "\u25b6",     # ▶
}


class BrowseMinimap(Widget):
    """1-cell wide minimap column showing anchor positions relative to scroll.

    Mounted inside OutputPanel with ``dock: right``. Textual pins docked
    widgets to the viewport edge — they do not scroll with content.
    """

    DEFAULT_CSS = """
    BrowseMinimap {
        width: 1;
        dock: right;
        background: $surface;
    }
    """

    def render_line(self, y: int) -> Strip:
        """Map viewport row y to a virtual content offset and draw anchor glyph."""
        app = self.app
        anchors = getattr(app, "_browse_anchors", [])
        cursor = getattr(app, "_browse_cursor", 0)

        if not anchors:
            return Strip([Segment(" ")])

        vh = self.size.height or 1
        try:
            from hermes_cli.tui.widgets import OutputPanel as _OP
            output = app.query_one(_OP)
            virtual_h = output.virtual_size.height or vh
        except Exception:
            virtual_h = vh

        if virtual_h == 0:
            return Strip([Segment(" ")])

        content_y = int(y / vh * virtual_h)
        band = max(1, virtual_h // vh)

        for i, anchor in enumerate(anchors):
            try:
                wy = anchor.widget.virtual_region.y
            except Exception:
                continue
            if content_y <= wy < content_y + band:
                glyph = _TYPE_GLYPH.get(
                    getattr(anchor.anchor_type, "value", ""),
                    "\u00b7",  # · fallback
                )
                style = Style(reverse=True) if i == cursor else Style(color="cyan")
                return Strip([Segment(glyph, style)])

        return Strip([Segment(" ")])
