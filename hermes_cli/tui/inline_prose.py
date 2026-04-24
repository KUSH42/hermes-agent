"""Inline prose rendering: mixed text + image span model and LRU image cache.

Consumed by InlineProseLog (widgets.py). Kept in its own module to allow
unit-testing the span model and cache independently of the widget layer.

Sections
--------
  TextSpan / ImageSpan / InlineLine  — span model (spec §5.1)
  _RenderMode                         — cache key (spec §5.2)
  _PaintOp                            — precomputed paint instruction (spec §5.4)
  InlineImageCache                    — pre-render + LRU-256 (spec §5.2, §5.10)
  _get_image_cache()                  — module-level singleton
"""

from __future__ import annotations

import logging
import sys
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.segment import Segment
from rich.text import Text
from textual.strip import Strip

if TYPE_CHECKING:
    from hermes_cli.tui.kitty_graphics import GraphicsCap

# ---------------------------------------------------------------------------
# § 5.1  Span model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextSpan:
    """Already-styled Rich Text fragment for use in an InlineLine."""
    text: Text


@dataclass(frozen=True)
class ImageSpan:
    """Image fragment for use in an InlineLine."""
    image_path: Path      # absolute path to image file
    cell_width: int       # rendered width in terminal cells
    cell_height: int = 1  # rendered height (only 1 supported initially; >1 deferred)
    alt_text: str = ""    # plain-text fallback for clipboard / search / no-image terminals
    cache_key: str = ""   # stable key; defaults to str(path) when empty


# Type aliases (not runtime generics — purely for readability)
InlineLine = list  # list[TextSpan | ImageSpan]


# ---------------------------------------------------------------------------
# § 5.2  _RenderMode — immutable cache-key component
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RenderMode:
    """Distinct renderer choice, used as part of the image cache key."""
    cap: GraphicsCap
    placeholders: bool = False  # True iff cap=TGP and Kitty unicode-placeholder mode active
    cell_px_w: int = 0          # cell pixel width at render time (resize invalidates)
    cell_px_h: int = 0          # cell pixel height at render time


# ---------------------------------------------------------------------------
# § 5.4  _PaintOp — one paint instruction for a visual row of an InlineLine
# ---------------------------------------------------------------------------

@dataclass
class _PaintOp:
    kind: Literal["text", "image"]
    text_segments: list[Segment] = field(default_factory=list)  # kind="text"
    span_index: int = -1                                         # kind="image": index into InlineLine
    image_row: int = 0                                           # which row of the image (0..cell_height-1)
    width: int = 0                                               # cell width contribution


# ---------------------------------------------------------------------------
# § 5.2 / § 5.10  Cache internals
# ---------------------------------------------------------------------------

_MAX_CACHE = 256


@dataclass
class _CacheEntry:
    strips: list[Strip]
    cap: GraphicsCap
    image_id: int = 0                                  # set for TGP/placeholder; 0 = no terminal state
    widget_ids: set[int] = field(default_factory=set)  # refcount by widget id


_sixel_warned: bool = False


# ---------------------------------------------------------------------------
# § 5.2  InlineImageCache
# ---------------------------------------------------------------------------

class InlineImageCache:
    """Pre-renders ImageSpan objects to per-row Strip lists.

    Cache key: (cache_key_str, cell_width, cell_height, _RenderMode).
    LRU-capped at 256 entries.
    TGP/placeholder entries emit Kitty delete sequences on eviction.
    Halfblock/NONE entries carry no terminal-side state.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple, _CacheEntry] = OrderedDict()

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def get_strips(
        self,
        span: ImageSpan,
        mode: _RenderMode,
        widget_id: int = 0,
    ) -> list[Strip]:
        """Return one Strip per cell_height row, each normalised to span.cell_width.

        May call _render() on cache miss — do NOT call from render_line.
        Use get_strips_or_alt() in render paths.
        """
        key = self._make_key(span, mode)
        if key in self._entries:
            self._entries.move_to_end(key)
            entry = self._entries[key]
            entry.widget_ids.add(widget_id)
            return entry.strips

        strips, image_id = self._render(span, mode)
        entry = _CacheEntry(
            strips=strips,
            cap=mode.cap,
            image_id=image_id,
            widget_ids={widget_id} if widget_id else set(),
        )
        self._entries[key] = entry
        self._evict_if_needed()
        return strips

    def get_strips_or_alt(
        self,
        span: ImageSpan,
        mode: _RenderMode,
        widget_id: int = 0,
    ) -> list[Strip]:
        """Return cached strips, or alt strips on cache miss. NEVER calls _render().

        Safe to call from render_line — no PIL operations, no terminal writes.
        On a cache miss the caller shows alt_text; a separate pre-render step
        (InlineProseLog._prerender_line_images) populates the cache and refreshes.
        """
        key = self._make_key(span, mode)
        if key in self._entries:
            self._entries.move_to_end(key)
            entry = self._entries[key]
            entry.widget_ids.add(widget_id)
            return entry.strips
        return self._alt_strips(span)

    def invalidate_for_resize(self) -> None:
        """Flush entries whose stored cell_px dims differ from current."""
        from hermes_cli.tui.kitty_graphics import _cell_px
        cw, ch = _cell_px()
        stale = [
            k for k in self._entries
            if k[3].cell_px_w != cw or k[3].cell_px_h != ch
        ]
        for k in stale:
            self._drop_entry(k)

    def decrement_refcount(self, span: ImageSpan, mode: _RenderMode, widget_id: int) -> None:
        """Called from InlineProseLog.on_unmount per referenced ImageSpan."""
        key = self._make_key(span, mode)
        if key not in self._entries:
            return
        entry = self._entries[key]
        entry.widget_ids.discard(widget_id)
        if not entry.widget_ids:
            self._drop_entry(key)

    def clear(self) -> None:
        for key in list(self._entries.keys()):
            self._drop_entry(key)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _make_key(self, span: ImageSpan, mode: _RenderMode) -> tuple:
        ck = span.cache_key or str(span.image_path)
        return (ck, span.cell_width, span.cell_height, mode)

    def _render(self, span: ImageSpan, mode: _RenderMode) -> tuple[list[Strip], int]:
        """Render span to strips using the given mode. Returns (strips, image_id)."""
        from hermes_cli.tui.kitty_graphics import (
            GraphicsCap,
            _load_image,
            _get_renderer,
            render_halfblock,
            transmit_only_sequence,
            build_tgp_placeholder_strips,
        )
        global _sixel_warned

        if span.cell_width <= 0 or span.cell_height <= 0:
            return [], 0

        if mode.cap == GraphicsCap.NONE:
            return self._alt_strips(span), 0

        img = _load_image(span.image_path)
        if img is None:
            return [], 0

        cw = mode.cell_px_w or 8
        ch = mode.cell_px_h or 16

        if mode.cap == GraphicsCap.TGP and mode.placeholders:
            try:
                from PIL import Image as PILImage
                img_rgba = img.convert("RGBA")
                img_resized = img_rgba.resize((span.cell_width * cw, span.cell_height * ch))
                renderer = _get_renderer()
                image_id = renderer._alloc_id()
                seq = transmit_only_sequence(image_id, img_resized, span.cell_width, span.cell_height)
                # sys.__stdout__ bypasses Textual's redirect_stdout(_PrintCapture) wrapper,
                # which would otherwise swallow the TGP sequence into app._print() instead
                # of writing it to the Kitty terminal.
                out = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout
                out.write(seq)
                out.flush()
                raw = build_tgp_placeholder_strips(image_id, span.cell_width, span.cell_height)
                result = [s.adjust_cell_length(span.cell_width) for s in raw[:span.cell_height]]
                while len(result) < span.cell_height:
                    result.append(Strip.blank(span.cell_width))
                return result, image_id
            except Exception:
                logger.debug(
                    "InlineImageCache: TGP render failed for span %r, using alt text",
                    span.alt_text, exc_info=True,
                )
                return self._alt_strips(span), 0

        if mode.cap == GraphicsCap.SIXEL and not _sixel_warned:
            _sixel_warned = True
            warnings.warn(
                "InlineImageCache: SIXEL cap → halfblock fallback for inline images",
                stacklevel=3,
            )

        # HALFBLOCK: fallback for TGP-without-placeholders, SIXEL, and HALFBLOCK cap
        try:
            from PIL import Image as PILImage
            img_rgba = img.convert("RGBA") if img.mode != "RGBA" else img
            img_resized = img_rgba.resize((span.cell_width * cw, span.cell_height * ch))
            rgb_img = PILImage.new("RGB", img_resized.size, (0, 0, 0))
            if img_resized.mode == "RGBA":
                rgb_img.paste(img_resized, mask=img_resized.split()[3])
            else:
                rgb_img.paste(img_resized)
            raw_strips = render_halfblock(rgb_img, max_cols=span.cell_width, max_rows=span.cell_height)
        except Exception:
            logger.debug(
                "InlineImageCache: halfblock render failed for span %r, using alt text",
                span.alt_text, exc_info=True,
            )
            return self._alt_strips(span), 0

        result = [s.adjust_cell_length(span.cell_width) for s in raw_strips[:span.cell_height]]
        while len(result) < span.cell_height:
            result.append(Strip.blank(span.cell_width))
        return result, 0

    def _alt_strips(self, span: ImageSpan) -> list[Strip]:
        alt = (span.alt_text or "?")[:span.cell_width].ljust(span.cell_width)
        return [Strip([Segment(alt)])] * span.cell_height

    def _drop_entry(self, key: tuple) -> None:
        entry = self._entries.pop(key, None)
        if entry and entry.image_id:
            try:
                sys.stdout.write(f"\x1b_Ga=d,d=I,i={entry.image_id},q=2\x1b\\")
                sys.stdout.flush()
            except Exception:
                logger.debug("InlineImageCache: kitty delete-image write failed", exc_info=True)

    def _evict_if_needed(self) -> None:
        while len(self._entries) > _MAX_CACHE:
            self._drop_entry(next(iter(self._entries)))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_image_cache: InlineImageCache | None = None


def _get_image_cache() -> InlineImageCache:
    global _image_cache
    if _image_cache is None:
        _image_cache = InlineImageCache()
    return _image_cache


def _reset_image_cache() -> None:
    """Test-only: discard and clear the singleton."""
    global _image_cache, _sixel_warned
    if _image_cache is not None:
        _image_cache.clear()
    _image_cache = None
    _sixel_warned = False
