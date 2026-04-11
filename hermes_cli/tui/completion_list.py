"""Virtualized completion list — O(viewport) per frame regardless of item count.

``VirtualCompletionList`` stores candidates in a flat ``tuple[Candidate, ...]``
reactive and implements ``render_line(y)`` to build ``Strip``s only for
visible rows.  ``virtual_size`` tells the compositor the full scroll extent.

Never create child widgets per item — that is the React/Yoga shape where
Textual is no faster than Ink.  The single ``render_line`` pull per visible
row is the asymmetry that makes 10k candidates at 60fps possible.

Correctness invariants (all load-bearing — do not remove):
1. ``layout=True`` on ``items`` reactive → layout pass when length changes.
2. ``virtual_size = Size(width, len(items))`` → scroll extents stay correct.
3. ``extend_cell_length`` BEFORE ``crop`` → selection bg covers full row width.
4. ``animate=False`` on ``scroll_to_region`` → no frame drops per keypress.
5. ``Style(bgcolor="blue")`` not ``Style(bgcolor="on_blue")`` → no ColorParseError.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.geometry import Region, Size
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

if TYPE_CHECKING:
    from .path_search import Candidate


# Class-level constant — avoids Style() construction cost per keystroke per row.
# ``bgcolor="blue"`` is Rich's literal color name; ``"on_blue"`` raises
# ColorParseError — the ``on_`` prefix is only valid inside Style.parse().
# Default matches $cursor-selection-bg in hermes.tcss (overridden by skin vars).
_SELECTED_STYLE = Style(bgcolor="#3A5A8C")

# Pre-built status rows for empty states (avoids allocation in hot render path)
_SEARCHING_TEXT = Text("  searching…", style="dim italic", overflow="ellipsis", no_wrap=True)
_NO_MATCH_TEXT  = Text("  no matches", style="dim italic", overflow="ellipsis", no_wrap=True)


class VirtualCompletionList(ScrollView, can_focus=True):
    """O(viewport) completion list.  Handles 10k+ items at 60fps.

    Backed by a flat ``tuple[Candidate, ...]``; renders lines on demand via
    ``render_line(y)``.  Never creates child widgets for items.  Polymorphic
    over candidate kinds (PathCandidate, SlashCandidate, …).
    """

    DEFAULT_CSS = """
    VirtualCompletionList {
        height: auto;
        max-height: 12;
    }
    """

    items: reactive[tuple["Candidate", ...]] = reactive(tuple, layout=True)
    highlighted: reactive[int] = reactive(-1)
    searching: reactive[bool] = reactive(False, repaint=True)

    def __init__(self) -> None:
        super().__init__()
        self.virtual_size = Size(0, 0)
        # Cached at mount; refreshed on theme reload via _refresh_fuzzy_color()
        self._fuzzy_match_style: str = "bold #FFD866"
        # Default matches $cursor-selection-bg; overridden by skin via _refresh_fuzzy_color()
        self._selected_style: Style = Style(bgcolor="#3A5A8C")

    def on_mount(self) -> None:
        self._refresh_fuzzy_color()

    def _refresh_fuzzy_color(self) -> None:
        """Sync fuzzy match highlight and selection colors from the active skin."""
        try:
            css = self.app.get_css_variables()
            color = css.get("fuzzy-match-color", "#FFD866")
            self._fuzzy_match_style = f"bold {color}"
            # Use cursor-selection-bg so selection colour matches the input cursor
            # selection style — consistent across completion list and input widget.
            sel = css.get("cursor-selection-bg", "#3A5A8C")
            self._selected_style = Style(bgcolor=sel)
        except Exception:
            pass

    def watch_items(self, new: "tuple[Candidate, ...]") -> None:
        # Refresh skin-derived colours on every completion update so hot-reloaded
        # skins take effect without requiring an app restart.
        self._refresh_fuzzy_color()
        width = max((len(c.display) for c in new), default=0) + 2
        self.virtual_size = Size(width, len(new))
        self.highlighted = 0 if new else -1
        self.refresh()

    def watch_highlighted(self, idx: int) -> None:
        if idx < 0:
            self.app.highlighted_candidate = None
            return
        self.scroll_to_region(
            Region(0, idx, max(self.size.width, 1), 1),
            animate=False,  # load-bearing: animation per keypress = frame drops
        )
        self.refresh()
        # Publish the selected candidate so PreviewPanel picks it up via the
        # HermesApp.highlighted_candidate watcher.  Polymorphic: only the
        # PathCandidate branch actually triggers preview load; SlashCandidate
        # hits the isinstance guard in the watcher and clears the panel.
        if 0 <= idx < len(self.items):
            self.app.highlighted_candidate = self.items[idx]
        else:
            self.app.highlighted_candidate = None

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        data_idx = y + scroll_y

        # Empty-state row: show a dim hint on the first line instead of blank.
        # "searching…" while the path walker is in flight; "no matches" once done.
        if not self.items:
            if y == 0:
                msg = _SEARCHING_TEXT if self.searching else _NO_MATCH_TEXT
                segs = list(msg.render(self.app.console))
                strip = Strip(segs, msg.cell_len)
                return strip.extend_cell_length(self.size.width)
            return Strip.blank(self.size.width)

        if data_idx < 0 or data_idx >= len(self.items):
            return Strip.blank(self.size.width)

        candidate = self.items[data_idx]
        is_selected = data_idx == self.highlighted
        text = self._styled_candidate(candidate, is_selected)

        segments = list(text.render(self.app.console))
        strip = Strip(segments, text.cell_len)
        # Order matters: extend FIRST so the selected background covers the
        # full row width, THEN crop to horizontal scroll window.  Cropping
        # first would leave an un-styled gap on short rows.
        strip = strip.extend_cell_length(self.size.width)
        if scroll_x:
            strip = strip.crop(scroll_x, scroll_x + self.size.width)
        if is_selected:
            strip = strip.apply_style(self._selected_style)
        return strip

    def _styled_candidate(self, c: "Candidate", selected: bool) -> Text:
        base_style = "" if selected else "dim"
        t = Text(overflow="ellipsis", no_wrap=True)
        last = 0
        for start, end in c.match_spans:
            if start > last:
                t.append(c.display[last:start], style=base_style)
            t.append(c.display[start:end], style=self._fuzzy_match_style)
            last = end
        if last < len(c.display):
            t.append(c.display[last:], style=base_style)
        return t
