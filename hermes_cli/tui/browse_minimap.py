"""BrowseMinimap — 1-cell wide anchor minimap docked right inside OutputPanel.

Renders one glyph per anchor type mapped from virtual scroll position to
viewport row. Toggle with \\ while browse mode is active.
"""

from __future__ import annotations

import logging

from rich.segment import Segment
from rich.style import Style
from textual.css.query import NoMatches
from textual.strip import Strip
from textual.widget import Widget

from hermes_cli.tui._browse_types import _BROWSE_TYPE_GLYPH_NARROW
from hermes_cli.tui.widgets import OutputPanel

_log = logging.getLogger(__name__)


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

    def __init__(self) -> None:
        super().__init__()
        self._accent_cached: str = "#7aa2f7"  # bundled default accent
        self._accent_dirty: bool = True
        self._full_miss_warned: bool = False  # set by full-miss warn latch

    def on_mount(self) -> None:
        try:
            self.app.register_skin_callback(self._on_skin_changed)
        except AttributeError:
            _log.debug("BrowseMinimap: app has no register_skin_callback", exc_info=True)
        # Accent is loaded lazily on first render_line call (_accent_dirty=True).
        # Calling _refresh_accent() here would invoke get_css_variables() during mount
        # which can queue extra screen refreshes and slow down pilot.pause() in tests.

    def _on_skin_changed(self, *_args: object, **_kwargs: object) -> None:
        self._accent_dirty = True
        self.refresh()

    def _refresh_accent(self) -> None:
        try:
            self._accent_cached = self.app.get_css_variables().get("accent", "#7aa2f7")
        except Exception:
            _log.debug("BrowseMinimap: accent lookup failed", exc_info=True)
        self._accent_dirty = False

    def render_line(self, y: int) -> Strip:
        """Map viewport row y to a virtual content offset and draw anchor glyph."""
        if self._accent_dirty:
            self._refresh_accent()

        app = self.app
        anchors = getattr(app, "_browse_anchors", [])
        cursor = getattr(app, "_browse_cursor", 0)

        if not anchors:
            return Strip([Segment(" ")])

        vh = self.size.height or 1
        try:
            output = app.query_one(OutputPanel)
            virtual_h = output.virtual_size.height
        except (AttributeError, NoMatches):
            _log.debug("BrowseMinimap.render_line: output panel query failed", exc_info=True)
            virtual_h = vh

        if not virtual_h:
            return Strip([Segment(" ")])

        content_y = int(y / vh * virtual_h)
        band = max(1, virtual_h // vh)
        upper = virtual_h if y == vh - 1 else content_y + band

        # Pass 1: collect all anchors whose wy falls in this row's band.
        in_band: list[tuple[int, object]] = []
        fail_count = 0
        for i, anchor in enumerate(anchors):
            try:
                wy = anchor.widget.virtual_region.y
            except (AttributeError, NoMatches) as exc:
                fail_count += 1
                _log.debug(
                    "BrowseMinimap: virtual_region lookup failed for anchor %d (%s)",
                    i, type(exc).__name__,
                )
                continue
            if content_y <= wy < upper:
                in_band.append((i, anchor))

        # Full-miss warning — log once, reset on partial success
        if anchors and fail_count == len(anchors) and not self._full_miss_warned:
            _log.warning(
                "BrowseMinimap: all %d anchors failed virtual_region lookup; "
                "rebuild_browse_anchors may be broken",
                len(anchors),
            )
            self._full_miss_warned = True
        elif fail_count < len(anchors):
            self._full_miss_warned = False

        if not in_band:
            return Strip([Segment(" ")])

        # Pass 2: prefer the cursor anchor; otherwise first in DOM order.
        chosen = next(((i, a) for i, a in in_band if i == cursor), in_band[0])
        i, anchor = chosen

        glyph = _BROWSE_TYPE_GLYPH_NARROW.get(
            getattr(anchor.anchor_type, "value", ""),
            "·",  # · fallback
        )
        style = Style(reverse=True) if i == cursor else Style(color=self._accent_cached)
        return Strip([Segment(glyph, style)])
