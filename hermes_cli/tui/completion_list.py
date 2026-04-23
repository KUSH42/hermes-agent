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

import os
from typing import TYPE_CHECKING

from rich.console import Segment
from rich.style import Style
from rich.text import Text
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .animation import AnimationClock, lerp_color

if TYPE_CHECKING:
    from .path_search import Candidate

# Shimmer character table: ascending density → visual "sweep" left-to-right.
_SHIMMER_CHARS = " ░▒▓▒░"
_SHIMMER_LEN   = len(_SHIMMER_CHARS)

# Pre-built status rows for empty states (avoids allocation in hot render path)
_NO_MATCH_PREFIX = "  no results"
_EMPTY_REASON_TEXT: dict[str, str] = {
    "":               "  no results",
    "too_short":      "  type 2+ chars to match",
    "no_results":     "  no results",
    "no_slash_match": "  no match — /help for list",
    "path_not_found": "  no such path — try @ alone",
    "loading":        "  loading…",
}
_SEARCHING_PLAIN = Text("  searching…", style="dim italic", overflow="ellipsis", no_wrap=True)


def _normalize_segments(segments: list[Segment]) -> list[Segment]:
    """Ensure all rendered segments carry a concrete Rich Style.

    Textual's monochrome filter assumes ``segment.style`` is never None.
    Rich may emit padding / spacer segments with ``style=None``, so normalize
    them at the boundary before constructing a Strip.
    """
    return [Segment(seg.text, seg.style or Style(), seg.control) for seg in segments]


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

    # --- Messages ---

    class AutoDismiss(Message):
        """Posted when the empty-state auto-close timer fires (P0-B).

        CompletionOverlay or HermesApp handles this to remove --visible.
        """

    # --- Reactives ---

    items: reactive[tuple["Candidate", ...]] = reactive(tuple, layout=True)
    highlighted: reactive[int] = reactive(-1)
    searching: reactive[bool] = reactive(False, repaint=True)
    empty_reason: reactive[str] = reactive("", repaint=True)

    # Shimmer animation phase (P0-A): incremented at 8 Hz while searching.
    _shimmer_phase: reactive[int] = reactive(0, repaint=True)

    def __init__(self) -> None:
        super().__init__()
        self.virtual_size = Size(0, 0)
        # Cached at mount; refreshed on theme reload via _refresh_fuzzy_color()
        self._fuzzy_match_style: str = "bold #FFD866"
        # Default matches $cursor-selection-bg; overridden by skin via _refresh_fuzzy_color()
        self._selected_style: Style = Style(bgcolor="#3A5A8C")
        self._shimmer_timer: object | None = None
        self._auto_close_timer: object | None = None
        # Current query fragment — set by _push_to_list; used in empty-state label.
        self.current_query: str = ""
        # NO_COLOR detection (cached at init, immutable).
        self._no_color: bool = bool(os.environ.get("NO_COLOR", "").strip())

    def on_mount(self) -> None:
        self._refresh_fuzzy_color()

    def on_unmount(self) -> None:
        self._stop_shimmer()
        self._cancel_auto_close()

    def _refresh_fuzzy_color(self) -> None:
        """Sync fuzzy match highlight, selection, and empty-state colors from the active skin."""
        try:
            css = self.app.get_css_variables()
            color = css.get("fuzzy-match-color", "#FFD866")
            self._fuzzy_match_style = f"bold {color}"
            # Use cursor-selection-bg so selection colour matches the input cursor
            # selection style — consistent across completion list and input widget.
            sel = css.get("cursor-selection-bg", "#3A5A8C")
            self._selected_style = Style(bgcolor=sel)
            empty_bg = css.get("completion-empty-bg", "#2A2000")
            self._completion_empty_bg: str = empty_bg
        except Exception:
            pass

    def refresh_theme(self) -> None:
        """Called by HermesApp.apply_skin() after a hot-reload.

        Forces re-read of CSS variables and triggers a repaint. Replaces the
        bare _refresh_fuzzy_color() call in apply_skin() — the added refresh()
        ensures the list repaints immediately with new colors rather than waiting
        for the next item-batch update.
        """
        self._refresh_fuzzy_color()
        self.refresh()

    # -------------------------------------------------------------------------
    # Shimmer (P0-A)
    # -------------------------------------------------------------------------

    def watch_searching(self, value: bool) -> None:
        """Start/stop the shimmer animation timer based on searching state."""
        if value:
            self._cancel_auto_close()
            self._start_shimmer()
        else:
            self._stop_shimmer()
            # Searching ended — evaluate auto-close if still empty (P0-B).
            self._maybe_schedule_auto_close()

    def _start_shimmer(self) -> None:
        if self._shimmer_timer is not None:
            return
        if getattr(self, "app", None) and self.app.has_class("reduced-motion"):
            return
        animations_on = getattr(getattr(self, "app", None), "_animations_enabled", True)
        if animations_on and not self._no_color:
            clock: AnimationClock | None = getattr(
                getattr(self, "app", None), "_anim_clock", None
            )
            if clock is not None:
                self._shimmer_timer = clock.subscribe(2, self._advance_shimmer)
            else:
                self._shimmer_timer = self.set_interval(1 / 8, self._advance_shimmer)

    def _stop_shimmer(self) -> None:
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._shimmer_phase = 0

    def _advance_shimmer(self) -> None:
        """Timer callback — plain def, no await."""
        self._shimmer_phase = (self._shimmer_phase + 1) % (_SHIMMER_LEN * 4)

    def _render_shimmer_row(self, y: int) -> Strip:
        """Render one ThinkingWidget-style block density sweep row (P0-A)."""
        if self._no_color:
            # Plain fallback for NO_COLOR terminals — only show on row 0.
            if y == 0:
                t = Text("  searching…", style="dim italic", no_wrap=True, overflow="ellipsis")
                segs = list(t.render(self.app.console))
                return Strip(segs).extend_cell_length(self.size.width)
            return Strip.blank(self.size.width)

        width = self.size.width or 40
        phase = self._shimmer_phase
        try:
            v = self.app.get_css_variables()
            app_bg = v.get("app-bg", "#1E1E1E")
        except Exception:
            app_bg = "#1E1E1E"
        trough = lerp_color(app_bg, "#000000", 0.3)
        peak   = lerp_color(app_bg, "#888888", 0.35)
        # Pre-parse trough/peak to RGB for batch lerp_color_rgb calls
        from hermes_cli.tui.animation import _parse_rgb, lerp_color_rgb
        trough_rgb = _parse_rgb(trough)
        peak_rgb = _parse_rgb(peak)
        # Stagger each row's phase by its y offset for a diagonal wave effect.
        row_phase = (phase + y * 2) % (_SHIMMER_LEN * 4)
        # Pre-compute chars and colors per position
        chars: list[str] = []
        colors: list[str] = []
        for x in range(width):
            idx = (x + row_phase) % _SHIMMER_LEN
            chars.append(_SHIMMER_CHARS[idx])
            brightness = idx / max(_SHIMMER_LEN - 1, 1)
            colors.append(lerp_color_rgb(trough_rgb, peak_rgb, brightness))
        # Batch consecutive same-color runs into single segments
        segments: list[Segment] = []
        run_start = 0
        run_color = colors[0]
        for i in range(1, width + 1):
            c = colors[i] if i < width else None
            if c != run_color:
                text = "".join(chars[run_start:i])
                segments.append(Segment(text, Style(color=run_color)))
                run_start = i
                run_color = c
        return Strip(segments).crop(0, width)

    # -------------------------------------------------------------------------
    # Auto-close (P0-B)
    # -------------------------------------------------------------------------

    def _cancel_auto_close(self) -> None:
        if self._auto_close_timer is not None:
            self._auto_close_timer.stop()
            self._auto_close_timer = None

    def _maybe_schedule_auto_close(self) -> None:
        """Schedule auto-dismiss if walk done and no items."""
        self._cancel_auto_close()
        if self.items or self.searching:
            return
        # no threshold — any empty result schedules close
        self._auto_close_timer = self.set_timer(1.5, self._fire_auto_dismiss)

    def _fire_auto_dismiss(self) -> None:
        self._auto_close_timer = None
        if not self.items and not self.searching:
            self.post_message(self.AutoDismiss())

    # -------------------------------------------------------------------------
    # Overflow badge (P0-F)
    # -------------------------------------------------------------------------

    def _update_overflow_badge(self) -> None:
        """Show/hide the #overflow-badge in CompletionOverlay (P0-F)."""
        from textual.css.query import NoMatches
        from textual.widgets import Static
        try:
            badge = self.app.query_one("#overflow-badge", Static)
        except NoMatches:
            return
        n = len(self.items)
        visible = self.size.height if self.size.height > 0 else 13
        if n > visible:
            badge.update(f"[dim]  ↓ {n - visible} more matches[/dim]")
            badge.display = True
        else:
            badge.display = False

    def on_resize(self, _event: object) -> None:
        self._update_overflow_badge()

    # -------------------------------------------------------------------------
    # Watchers
    # -------------------------------------------------------------------------

    def watch_items(self, old: "tuple[Candidate, ...]", new: "tuple[Candidate, ...]") -> None:
        # Refresh skin-derived colours once per completion session (empty → non-empty)
        # so hot-reloaded skins take effect without paying get_css_variables() overhead
        # on every item-batch update (critical for the 10k-item perf path).
        if new and not old:
            self._refresh_fuzzy_color()
        if new:
            self.empty_reason = ""  # Clear reason when results arrive
        width = max((len(c.display) for c in new), default=0) + 2
        # When searching with no results yet, keep virtual_size at least 1 row
        # so the shimmer/searching indicator is visible.  Without this,
        # height:auto overlay collapses to 0 when virtual_size.height=0.
        height = max(len(new), 1 if self.searching else 0)
        self.virtual_size = Size(max(width, 20), height)
        self.highlighted = 0 if new else -1
        self.refresh()

        # P0-F: update pinned badge
        self._update_overflow_badge()

        # P0-B: auto-close on persistent zero results
        if new:
            self._cancel_auto_close()
        elif not self.searching:
            self._maybe_schedule_auto_close()

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

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        data_idx = y + scroll_y

        if not self.items:
            # P0-A: shimmer while walk in flight
            if self.searching:
                return self._render_shimmer_row(y)
            # P0-B: empty-state row
            if y == 0:
                query = self.current_query
                reason = self.empty_reason
                base_label = _EMPTY_REASON_TEXT.get(reason, _NO_MATCH_PREFIX)
                label = (f'{base_label} for \u201c{query}\u201d' if query and reason == "" else base_label)
                t = Text(label, style="dim italic", overflow="ellipsis", no_wrap=True)
                segs = _normalize_segments(list(t.render(self.app.console)))
                strip = Strip(segs, t.cell_len)
                strip = strip.extend_cell_length(self.size.width)
                empty_bg = getattr(self, "_completion_empty_bg", "#2A2000")
                strip = strip.apply_style(Style(bgcolor=empty_bg))
                return strip
            return Strip.blank(self.size.width)

        if data_idx < 0 or data_idx >= len(self.items):
            return Strip.blank(self.size.width)

        candidate = self.items[data_idx]
        is_selected = data_idx == self.highlighted
        text = self._styled_candidate(candidate, is_selected)

        segments = _normalize_segments(list(text.render(self.app.console)))
        strip = Strip(segments, text.cell_len)
        # Order matters: extend FIRST so the selected background covers the
        # full row width, THEN crop to horizontal scroll window.  Cropping
        # first would leave an un-styled gap on short rows.
        strip = strip.extend_cell_length(self.size.width)
        strip = Strip(_normalize_segments(list(strip)), strip.cell_length)
        if scroll_x:
            strip = strip.crop(scroll_x, scroll_x + self.size.width)
        if is_selected:
            strip = strip.apply_style(self._selected_style)
        return strip

    def _styled_candidate(self, c: "Candidate", selected: bool) -> Text:
        from .path_search import PathCandidate
        base_style = Style() if selected else Style(dim=True)
        t = Text(overflow="ellipsis", no_wrap=True)
        last = 0
        for start, end in c.match_spans:
            if start > last:
                t.append(c.display[last:start], style=base_style)
            t.append(c.display[start:end], style=self._fuzzy_match_style)
            last = end
        if last < len(c.display):
            t.append(c.display[last:], style=base_style)
        # C5: show insert_text suffix when it differs from display (not on selected row)
        if (
            not selected
            and isinstance(c, PathCandidate)
            and c.insert_text
            and c.insert_text != c.display
        ):
            t.append(f"  →  {c.insert_text}", style=Style(dim=True, color="#888888"))
        return t
