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

    Mounted as a ``dock: right`` child of ``OutputPanel``. In Textual 8.x,
    dock children of a ``ScrollableContainer`` are positioned within the
    container's viewport (not its scroll content), so the minimap stays pinned
    to the right edge. Verified by ``test_minimap_is_viewport_pinned``.
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
        self._viewport_rect_enabled: bool = True
        self._viewport_bg_cached: str = "#1e2030"  # bundled default panel-darken-1

    def on_mount(self) -> None:
        try:
            self.app.register_skin_callback(self._on_skin_changed)
        except AttributeError:
            _log.debug("BrowseMinimap: app has no register_skin_callback", exc_info=True)
        # Accent is loaded lazily on first render_line call (_accent_dirty=True).
        # Calling _refresh_accent() here would invoke get_css_variables() during mount
        # which can queue extra screen refreshes and slow down pilot.pause() in tests.

        # Read config flag once at mount (not hot-reloaded, consistent with other browse_markers flags).
        self._viewport_rect_enabled = bool(
            getattr(self.app, "_browse_minimap_viewport_rect", True)
        )

        # Cache viewport bg color from skin variables.
        try:
            self._viewport_bg_cached = self.app.get_css_variables().get(
                "panel-darken-1", "#1e2030"
            )
        except Exception:
            _log.debug("BrowseMinimap: viewport bg lookup failed", exc_info=True)

        # Subscribe to output panel scroll changes to keep viewport rect fresh.
        if self._viewport_rect_enabled:
            try:
                output = self.app.query_one(OutputPanel)
                self.watch(output, "scroll_y", self._on_output_scroll, init=False)
            except (NoMatches, AttributeError):
                _log.debug("BrowseMinimap.on_mount: could not watch output scroll_y", exc_info=True)

    def _on_skin_changed(self, *_args: object, **_kwargs: object) -> None:
        self._accent_dirty = True
        try:
            self._viewport_bg_cached = self.app.get_css_variables().get(
                "panel-darken-1", "#1e2030"
            )
        except Exception:
            _log.debug("BrowseMinimap: viewport bg refresh failed on skin change", exc_info=True)
        self.refresh()

    def _on_output_scroll(self, *_args: object) -> None:
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
            try:
                self._accent_cached = self.app.get_css_variables().get("accent", "cyan")
            except Exception:
                _log.debug("BrowseMinimap: accent lookup failed", exc_info=True)
                self._accent_cached = "cyan"
            self._accent_dirty = False

        app = self.app
        anchors = getattr(app, "_browse_anchors", [])
        cursor = getattr(app, "_browse_cursor", 0)

        viewport_rect_enabled = bool(getattr(self, "_viewport_rect_enabled", False))

        if not anchors and not viewport_rect_enabled:
            return Strip([Segment(" ")])

        vh = self.size.height or 1
        try:
            output = app.query_one(OutputPanel)
            virtual_h = output.virtual_size.height
            scroll_y = int(output.scroll_y)
        except (AttributeError, NoMatches):
            _log.debug("BrowseMinimap.render_line: output panel query failed", exc_info=True)
            virtual_h = vh
            scroll_y = 0

        if not virtual_h:
            return Strip([Segment(" ")])

        content_y = int(y / vh * virtual_h)
        band = max(1, virtual_h // vh)
        upper = virtual_h if y == vh - 1 else content_y + band

        # Config-gated viewport rectangle (MMP-H4). Skip entirely when off.
        if viewport_rect_enabled:
            in_viewport = not (upper <= scroll_y or content_y >= scroll_y + vh)
            vp_bg = self._viewport_bg_cached
        else:
            in_viewport = False
            vp_bg = None

        if not anchors:
            if in_viewport:
                return Strip([Segment(" ", Style(bgcolor=vp_bg))])
            return Strip([Segment(" ")])

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
            if in_viewport:
                return Strip([Segment(" ", Style(bgcolor=vp_bg))])
            return Strip([Segment(" ")])

        # Pass 2: prefer the cursor anchor; otherwise first in DOM order.
        chosen = next(((i, a) for i, a in in_band if i == cursor), in_band[0])
        i, anchor = chosen

        glyph = _BROWSE_TYPE_GLYPH_NARROW.get(
            getattr(anchor.anchor_type, "value", ""),
            "·",  # · fallback
        )
        if i == cursor:
            # Reverse style — inverts the bg tint naturally when in viewport.
            style = Style(reverse=True)
        elif in_viewport:
            style = Style(color=self._accent_cached, bgcolor=vp_bg)
        else:
            style = Style(color=self._accent_cached)
        return Strip([Segment(glyph, style)])
