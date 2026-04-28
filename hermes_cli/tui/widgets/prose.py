"""Prose and math display widgets for the Hermes TUI.

Contains: InlineProseLog, MathBlockWidget.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from .renderers import CopyableRichLog, _apply_span_style

if TYPE_CHECKING:
    pass


class InlineProseLog(CopyableRichLog):
    """CopyableRichLog subclass that supports mixed text + image inline lines.

    Lines added via write_inline(InlineLine) are rendered with images
    embedded at their x-position rather than as sibling widgets.

    Plain write() / write_with_source() calls take a zero-overhead code path
    identical to CopyableRichLog.
    """

    DEFAULT_CSS = "InlineProseLog { height: auto; overflow-y: hidden; overflow-x: hidden; }"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from hermes_cli.tui.inline_prose import _get_image_cache
        # Maps logical-line index → InlineLine (sparse; only inline lines have keys)
        self._inline_lines: dict[int, list] = {}
        # Maps logical-line index → list of visual-row paint plans
        self._inline_paint: dict[int, list[list]] = {}
        # Total logical lines written (our own counter; RichLog has no line_count)
        self._logical_count: int = 0
        # Visual row count per logical line (tracked in write() override)
        self._logical_visual_rows: dict[int, int] = {}
        self._image_cache = _get_image_cache()
        self._last_cell_px: tuple[int, int] = (0, 0)
        # Cached _RenderMode — avoids ioctl on every render_line call.
        # Set to None to force recompute on first use or after resize.
        self._render_mode_cache: "Any | None" = None

    # ------------------------------------------------------------------ #
    # Write API
    # ------------------------------------------------------------------ #

    def write_inline(self, line: list) -> None:  # line: InlineLine
        """Append a mixed-content line. Images are rendered at their x-offset.

        plain write() / write_with_source() continue to work unchanged.
        After writing, images are pre-rendered so render_line always reads from
        cache (never runs PIL or emits terminal sequences inside the render path).
        """
        from hermes_cli.tui.inline_prose import ImageSpan
        text = self._line_to_text(line)
        plain = self._line_to_plain(line)
        line_index = self._logical_count  # incremented by write() below
        self._inline_lines[line_index] = line
        self._inline_paint[line_index] = self._build_paint_plan(line, text)
        # super().write_with_source() → self.write() → increments _logical_count
        super().write_with_source(text, plain)
        # Pre-render images outside of render_line to avoid PIL/stdout writes
        # during Textual's render phase (which causes kitty screen glitches).
        has_images = any(isinstance(s, ImageSpan) for s in line)
        if has_images:
            self._prerender_line_images(line_index, line)

    def write(  # type: ignore[override]
        self,
        content: Any,
        width: "int | None" = None,
        expand: bool = True,
        shrink: bool = True,
        scroll_end: "bool | None" = None,
        animate: bool = False,
        *,
        _deferred: bool = False,
    ) -> "InlineProseLog":
        """Track visual row count for each logical line, then delegate."""
        idx = self._logical_count
        before = len(self.lines)
        result = super().write(
            content,
            width=width,
            expand=expand,
            shrink=shrink,
            scroll_end=scroll_end,
            animate=animate,
            _deferred=_deferred,
        )
        after = len(self.lines)
        delta = after - before
        # If write was deferred (pre-mount), delta == 0; fallback to 1 later via .get(idx, 1)
        if delta > 0:
            self._logical_visual_rows[idx] = delta
        self._logical_count += 1
        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # render_line — dispatch
    # ------------------------------------------------------------------ #

    def render_line(self, y: int) -> Strip:
        """Dispatch to inline renderer only when visual row belongs to an InlineLine."""
        scroll_x, scroll_y = self.scroll_offset
        content_y = scroll_y + y
        owner_index, row_in_line = self._owner_line_for_visual_y(content_y)
        if owner_index in self._inline_lines:
            return self._render_inline_line(owner_index, row_in_line, scroll_x, content_y)
        return super().render_line(y)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def on_resize(self, event: Any) -> None:
        """Invalidate image cache + render mode cache; rebuild paint plans when cell_px changes."""
        from hermes_cli.tui.kitty_graphics import _cell_px, _reset_cell_px_cache
        _reset_cell_px_cache()
        self._render_mode_cache = None  # force recompute with new cell dims
        new_px = _cell_px()
        if new_px != self._last_cell_px:
            self._last_cell_px = new_px
            self._image_cache.invalidate_for_resize()
            for idx, iline in list(self._inline_lines.items()):
                plan = self._build_paint_plan(iline, self._line_to_text(iline))
                self._inline_paint[idx] = plan
                self._logical_visual_rows[idx] = max(len(plan), 1)
            # Re-pre-render all inline lines with updated cell dims
            for idx, iline in list(self._inline_lines.items()):
                self._prerender_line_images(idx, iline)
        self.refresh()

    def on_unmount(self) -> None:
        """Decrement refcounts in the image cache; emit TGP deletions when last ref drops."""
        mode = self._current_render_mode()
        wid = id(self)
        for iline in self._inline_lines.values():
            for span in iline:
                from hermes_cli.tui.inline_prose import ImageSpan
                if isinstance(span, ImageSpan):
                    self._image_cache.decrement_refcount(span, mode, wid)

    # ------------------------------------------------------------------ #
    # get_selection — prefer _plain_lines for inline lines
    # ------------------------------------------------------------------ #

    def get_selection(self, selection: "Selection") -> "tuple[str, str] | None":
        """For lines in _inline_lines, always read from _plain_lines (alt_text subs)."""
        has_inline = bool(self._inline_lines)
        if has_inline:
            if self._plain_lines:
                text = "\n".join(self._plain_lines)
            else:
                return None
            return selection.extract(text), "\n"
        return super().get_selection(selection)

    # ------------------------------------------------------------------ #
    # Image pre-render — keeps render_line free of PIL ops / stdout writes
    # ------------------------------------------------------------------ #

    def _prerender_line_images(self, line_index: int, line: list) -> None:
        """Pre-populate cache for all ImageSpans in *line*.

        TGP path: emits the Kitty TGP sequence to stdout on the event loop
        (before render_line runs) so the image data arrives at the terminal
        before placeholder characters are drawn.

        Halfblock path: offloads PIL resize to a worker thread; render_line
        shows alt_text until the worker finishes and calls refresh().
        """
        from hermes_cli.tui.inline_prose import ImageSpan
        from hermes_cli.tui.kitty_graphics import GraphicsCap
        mode = self._current_render_mode()
        wid = id(self)
        hb_spans: list = []
        rendered_tgp = False
        for span in line:
            if not isinstance(span, ImageSpan):
                continue
            if mode.cap == GraphicsCap.TGP:
                # Emit TGP sequence synchronously here (safe — we are on the
                # event loop but NOT inside render_line's call stack).
                self._image_cache.get_strips(span, mode, wid)
                rendered_tgp = True
            else:
                hb_spans.append(span)
        if hb_spans:
            # @work requires an app context; skip silently when not mounted
            # (e.g. unit tests). render_line shows alt_text until repaint.
            try:
                self._prerender_halfblock(mode, wid, hb_spans)
            except Exception:
                # Markdown render failed; prose widget shows empty content
                pass
        elif rendered_tgp:
            self.refresh()

    @work(thread=True, exclusive=False)
    def _prerender_halfblock(self, mode: "Any", wid: int, spans: "list") -> None:
        """Worker: PIL resize for halfblock emoji renders, then trigger repaint."""
        from hermes_cli.tui.inline_prose import ImageSpan
        for span in spans:
            if isinstance(span, ImageSpan):
                self._image_cache.get_strips(span, mode, wid)
        self.app.call_from_thread(self.refresh)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _line_to_text(self, line: list) -> Text:
        """Convert InlineLine to Rich Text. ImageSpans → spaces with sentinel meta."""
        from hermes_cli.tui.inline_prose import ImageSpan
        result = Text(no_wrap=False)
        for i, span in enumerate(line):
            if isinstance(span, ImageSpan):
                placeholder = " " * span.cell_width
                result.append(placeholder, style=Style(meta={"__inline_image_idx__": i}))
            else:
                result.append_text(span.text)
        return result

    def _line_to_plain(self, line: list) -> str:
        """Convert InlineLine to plain string (alt_text for images)."""
        from hermes_cli.tui.inline_prose import ImageSpan
        parts: list[str] = []
        for span in line:
            if isinstance(span, ImageSpan):
                parts.append(span.alt_text or "")
            else:
                parts.append(span.text.plain)
        return "".join(parts)

    def _current_render_mode(self) -> "Any":  # -> _RenderMode
        """Build (or return cached) _RenderMode based on detected terminal caps.

        Uses cell_width_px()/cell_height_px() (cached) instead of _cell_px()
        (raw ioctl) to avoid a syscall on every render_line invocation.
        Cache is invalidated by on_resize().
        """
        if self._render_mode_cache is not None:
            return self._render_mode_cache
        from hermes_cli.tui.kitty_graphics import (
            get_caps, GraphicsCap, cell_width_px, cell_height_px,
            _supports_unicode_placeholders,
        )
        from hermes_cli.tui.inline_prose import _RenderMode
        cap = get_caps()
        cw, ch = cell_width_px(), cell_height_px()
        placeholders = (cap == GraphicsCap.TGP and _supports_unicode_placeholders())
        self._render_mode_cache = _RenderMode(
            cap=cap, placeholders=placeholders, cell_px_w=cw, cell_px_h=ch,
        )
        return self._render_mode_cache

    def _build_paint_plan(self, line: list, synth_text: Text) -> list[list]:
        """Pre-compute paint ops for line at current widget width.

        Renders synth_text through Rich Console at widget width to get the
        visual-row split. Segments carrying __inline_image_idx__ meta map to
        _PaintOp(kind="image"), all others to _PaintOp(kind="text").
        """
        from rich.cells import cell_len
        from rich.console import Console
        from hermes_cli.tui.inline_prose import _PaintOp

        width = self.scrollable_content_region.width or 80
        console = Console(width=width, force_terminal=True, highlight=False, markup=False)
        opts = console.options.update(width=width, no_wrap=False)
        raw_segs = list(console.render(synth_text, opts))
        rows = list(Segment.split_lines(raw_segs))

        paint_plan: list[list[_PaintOp]] = []
        for row_segs in rows:
            ops: list[_PaintOp] = []
            i = 0
            while i < len(row_segs):
                seg = row_segs[i]
                meta: dict = (getattr(seg.style, "meta", None) or {}) if seg.style else {}
                img_idx = meta.get("__inline_image_idx__")
                if img_idx is not None:
                    w = cell_len(seg.text)
                    ops.append(_PaintOp(kind="image", span_index=img_idx, image_row=0, width=w))
                    i += 1
                else:
                    text_segs: list[Segment] = []
                    while i < len(row_segs):
                        s = row_segs[i]
                        s_meta: dict = (getattr(s.style, "meta", None) or {}) if s.style else {}
                        if "__inline_image_idx__" in s_meta:
                            break
                        text_segs.append(s)
                        i += 1
                    if text_segs:
                        total_w = sum(cell_len(s.text) for s in text_segs)
                        ops.append(_PaintOp(kind="text", text_segments=text_segs, width=total_w))
            paint_plan.append(ops)

        return paint_plan if paint_plan else [[]]

    def _render_inline_line(
        self,
        owner_index: int,
        row_in_line: int,
        scroll_x: int,
        content_y: int,
    ) -> Strip:
        """Assemble Strip for one visual row of an InlineLine."""
        from hermes_cli.tui.inline_prose import ImageSpan, _PaintOp

        width = self.scrollable_content_region.width or 80
        plan_rows = self._inline_paint.get(owner_index, [])
        if row_in_line >= len(plan_rows):
            return Strip.blank(width).apply_style(self.rich_style)

        spans = self._inline_lines[owner_index]
        mode = self._current_render_mode()
        ops = plan_rows[row_in_line]
        wid = id(self)

        segments: list[Segment] = []
        for op in ops:
            if op.kind == "text":
                segments.extend(op.text_segments)
            else:
                span = spans[op.span_index]
                if not isinstance(span, ImageSpan):
                    continue
                strips = self._image_cache.get_strips_or_alt(span, mode, wid)
                if strips and op.image_row < len(strips):
                    img_strip = strips[op.image_row]
                    if op.width != span.cell_width:
                        img_strip = img_strip.crop(0, op.width)
                    segments.extend(img_strip)
                else:
                    alt = (span.alt_text or "?")
                    seg_text = alt[:op.width].ljust(op.width)
                    segments.append(Segment(seg_text))

        strip = Strip(segments).simplify().adjust_cell_length(width).apply_style(self.rich_style)

        selection = self.text_selection
        if selection is not None:
            sel_span = selection.get_span(content_y)
            if sel_span is not None:
                try:
                    sel_style = self.screen.get_component_rich_style("screen--selection")
                    strip = _apply_span_style(strip, sel_span[0], sel_span[1], sel_style)
                except Exception:
                    # Rich markup render failed; prose widget shows empty content
                    pass

        return strip.apply_offsets(scroll_x, content_y)

    def _owner_line_for_visual_y(self, content_y: int) -> tuple[int, int]:
        """Map a content-row index to (logical_line_index, row_in_line).

        Returns (-1, 0) for plain text lines (caller falls back to parent render_line).
        """
        cumulative = 0
        for logical_idx in range(self._logical_count):
            if logical_idx in self._inline_paint:
                n_rows = len(self._inline_paint[logical_idx])
            else:
                n_rows = self._logical_visual_rows.get(logical_idx, 1)
            if cumulative + n_rows > content_y:
                is_inline = logical_idx in self._inline_lines
                return (logical_idx if is_inline else -1, content_y - cumulative)
            cumulative += n_rows
        return (-1, 0)


class MathBlockWidget(Widget):
    """Rendered block-math formula: label + InlineImage child."""

    DEFAULT_CSS = """
    MathBlockWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
        border-left: vkey $accent 40%;
    }
    MathBlockWidget .--math-label {
        color: $text-muted;
    }
    """

    def __init__(self, image_path: Path, max_rows: int = 12, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._image_path = image_path
        self._max_rows = max_rows

    def compose(self) -> ComposeResult:
        from hermes_cli.tui.widgets.inline_media import InlineImage
        yield Static("∫ Math expression", classes="--math-label")
        yield InlineImage(image=self._image_path, max_rows=self._max_rows)

    def copy_content(self) -> str:
        """Return the image path as a hint (original LaTeX not retained here)."""
        return str(self._image_path)
