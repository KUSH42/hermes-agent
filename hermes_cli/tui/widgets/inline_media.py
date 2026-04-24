"""Inline media display widgets for the Hermes TUI.

Contains: InlineImage, InlineThumbnail, InlineImageBar.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tooltip import TooltipMixin

if TYPE_CHECKING:
    pass


class InlineImage(Widget):
    """Display an image inline using TGP, halfblock, or text placeholder."""

    DEFAULT_CSS = """
    InlineImage {
        width: 100%;
        height: auto;
    }
    """

    image: reactive = reactive(None)
    max_rows: reactive = reactive(24)

    def __init__(
        self,
        image: "Any" = None,
        max_rows: int = 24,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._image_id: int | None = None
        self._rendered_rows: int = 1
        self._tgp_seq: str = ""
        self._tgp_transmitted: bool = False
        self._tgp_placeholder_strips: list[Strip] = []
        self._sixel_seq: str = ""
        self._halfblock_strips: list[Strip] = []
        self._src_path: str = ""
        self._pending_image = image
        self.max_rows = max_rows

    def on_mount(self) -> None:
        if self._pending_image is not None:
            self.image = self._pending_image

    def watch_image(self, new_image: "Any") -> None:
        from hermes_cli.tui.kitty_graphics import (
            GraphicsCap,
            _load_image,
            _supports_unicode_placeholders,
            get_caps,
            get_inline_images_mode,
        )
        if new_image is None or get_inline_images_mode() == "off":
            self._tgp_seq = ""
            self._tgp_transmitted = False
            self._tgp_placeholder_strips = []
            self._sixel_seq = ""
            self._halfblock_strips = []
            self._rendered_rows = 1
            self.styles.height = 1
            self.refresh()
            return
        if isinstance(new_image, (str, Path)):
            self._src_path = str(new_image)
        img = _load_image(new_image)
        if img is None:
            self._tgp_seq = ""
            self._tgp_transmitted = False
            self._tgp_placeholder_strips = []
            self._sixel_seq = ""
            self._halfblock_strips = []
            self._rendered_rows = 1
            self.styles.height = 1
            self.refresh()
            return
        cap = get_caps()
        if cap == GraphicsCap.TGP and _supports_unicode_placeholders():
            self._prepare_tgp(img)
        elif cap in (GraphicsCap.TGP, GraphicsCap.SIXEL, GraphicsCap.HALFBLOCK):
            if cap == GraphicsCap.TGP:
                import logging as _logging
                _LOG = _logging.getLogger(__name__)
                _LOG.warning(
                    "TGP detected but unicode placeholders unavailable "
                    "(TERM=%r, KITTY_WINDOW_ID=%r) — falling back to halfblock",
                    os.environ.get("TERM", ""),
                    os.environ.get("KITTY_WINDOW_ID", ""),
                )
            self._prepare_halfblock(img)
        else:
            self._rendered_rows = 1
            self.styles.height = 1
        self.refresh()

    def _prepare_tgp(self, img: "Any") -> None:
        from hermes_cli.tui.kitty_graphics import LARGE_IMAGE_BYTES, _get_renderer
        if self._image_id is not None:
            self._emit_raw(_get_renderer().delete_sequence(self._image_id))
            self._image_id = None
        self._tgp_transmitted = False
        self._tgp_placeholder_strips = []
        if img.width * img.height * 4 > LARGE_IMAGE_BYTES:
            self._prepare_tgp_async(img)
        else:
            self._apply_tgp_result(*self._encode_tgp_placeholder(img))

    @work(thread=True)
    def _prepare_tgp_async(self, img: "Any") -> None:
        """Encode large images off the event loop to avoid blocking the UI."""
        try:
            result = self._encode_tgp_placeholder(img)
        except Exception:
            return
        if self.is_mounted:
            self.app.call_from_thread(self._apply_tgp_result, *result)

    def _encode_tgp_placeholder(self, img: "Any") -> tuple[str, int, int, int]:
        from hermes_cli.tui.kitty_graphics import (
            _cell_px,
            _fit_image,
            _get_renderer,
            transmit_only_sequence,
        )
        renderer = _get_renderer()
        max_cols = self.size.width or 80
        cw, ch = _cell_px()
        resized, cols, rows = _fit_image(img.convert("RGBA"), max_cols, self.max_rows, cw, ch)
        image_id = renderer._alloc_id()
        seq = transmit_only_sequence(image_id, resized, cols, rows)
        return seq, image_id, cols, rows

    def _apply_tgp_result(self, seq: str, image_id: int, cols: int, rows: int) -> None:
        """Transmit TGP out-of-band and render unicode placeholder strips."""
        if not self.is_mounted:
            return
        from hermes_cli.tui.kitty_graphics import build_tgp_placeholder_strips
        self._emit_raw(seq)
        self._tgp_seq = seq
        self._image_id = image_id
        self._tgp_transmitted = True
        self._tgp_placeholder_strips = build_tgp_placeholder_strips(image_id, cols, rows)
        self._rendered_rows = rows
        self.styles.height = rows
        self.refresh()

    def _prepare_halfblock(self, img: "Any") -> None:
        from hermes_cli.tui.kitty_graphics import render_halfblock
        max_cols = self.size.width or 80
        self._halfblock_strips = render_halfblock(img, max_cols, self.max_rows)
        self._tgp_transmitted = False
        self._tgp_placeholder_strips = []
        self._sixel_seq = ""
        self._rendered_rows = len(self._halfblock_strips)
        self.styles.height = self._rendered_rows

    def _prepare_sixel(self, img: "Any") -> None:
        from hermes_cli.tui.kitty_graphics import _to_sixel, _cell_px, _fit_image
        cw, ch = _cell_px()
        max_cols = self.size.width or 80
        seq = _to_sixel(img, max_cols=max_cols, max_rows=self.max_rows)
        self._sixel_seq = seq
        if seq and cw > 0 and ch > 0:
            _, _cols, rows = _fit_image(img.convert("RGBA"), max_cols, self.max_rows, cw, ch)
            self._rendered_rows = rows
            self.styles.height = rows

    def render_line(self, y: int) -> Strip:
        from hermes_cli.tui.kitty_graphics import GraphicsCap, get_caps
        cap = get_caps()
        if cap == GraphicsCap.TGP and self._tgp_placeholder_strips:
            return self._render_tgp_line(y)
        if cap in (GraphicsCap.TGP, GraphicsCap.SIXEL, GraphicsCap.HALFBLOCK):
            return self._render_halfblock_line(y)
        return self._render_placeholder_line(y)

    def _render_tgp_line(self, y: int) -> Strip:
        if y >= len(self._tgp_placeholder_strips):
            return Strip.blank(self.size.width or 80)
        return self._tgp_placeholder_strips[y]

    def _render_sixel_line(self, y: int) -> Strip:
        return self._render_halfblock_line(y)

    def _render_halfblock_line(self, y: int) -> Strip:
        if y >= len(self._halfblock_strips):
            return Strip.blank(self.size.width or 80)
        return self._halfblock_strips[y]

    def _render_placeholder_line(self, y: int) -> Strip:
        if y == 0:
            txt = f"[image: {self._src_path or '?'}]"
            return Strip([Segment(txt)])
        return Strip.blank(self.size.width or 80)

    def _emit_raw(self, seq: str) -> None:
        try:
            sys.stdout.write(seq)
            sys.stdout.flush()
        except Exception:
            pass

    def on_unmount(self) -> None:
        from hermes_cli.tui.kitty_graphics import _get_renderer
        if self._image_id is not None:
            self._emit_raw(_get_renderer().delete_sequence(self._image_id))
            self._image_id = None

    def on_resize(self, event: object) -> None:
        if self.image is not None:
            self.watch_image(self.image)


class InlineThumbnail(TooltipMixin, Widget):
    """Clickable halfblock thumbnail inside InlineImageBar."""

    DEFAULT_CSS = """
    InlineThumbnail {
        width: 10;
        height: 6;
        margin: 0 1;
        border: solid $panel-lighten-1;
    }
    InlineThumbnail:hover {
        border: solid $accent;
    }
    """

    _tooltip_text = "Click to scroll to image"

    def __init__(self, path: str, index: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._path = path
        self._index = index
        self._strips: list[Strip] = []

    def on_mount(self) -> None:
        self._load_strips()

    @work(thread=True)
    def _load_strips(self) -> None:
        from hermes_cli.tui.kitty_graphics import _load_image, render_halfblock
        img = _load_image(self._path)
        if img is not None:
            strips = render_halfblock(img, max_cols=10, max_rows=6)
        else:
            strips = []
        self.app.call_from_thread(self._apply_strips, strips)

    def _apply_strips(self, strips: list[Strip]) -> None:
        self._strips = strips
        self.refresh()

    def render_line(self, y: int) -> Strip:
        if y < len(self._strips):
            return self._strips[y]
        return Strip.blank(self.size.width or 10)

    def on_click(self) -> None:
        self.post_message(InlineImageBar.ThumbnailClicked(self._path, self._index))


class InlineImageBar(Widget):
    """Horizontal strip of image thumbnails for inline images. Hidden when empty."""

    class ThumbnailClicked(Message):
        def __init__(self, path: str, index: int) -> None:
            super().__init__()
            self.path = path
            self.index = index

    DEFAULT_CSS = """
    InlineImageBar {
        height: 7;
        width: 100%;
        display: none;
        overflow-x: scroll;
        overflow-y: hidden;
        background: $panel;
        border-top: solid $panel-lighten-1;
        padding: 0 1;
    }
    InlineImageBar.--visible {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._paths: list[str] = []
        self._enabled: bool = True

    def compose(self) -> ComposeResult:
        yield Horizontal()

    def add_image(self, path: str) -> None:
        """Add a thumbnail. No-op when display.image_bar is disabled."""
        if not self._enabled:
            return
        self._paths.append(path)
        idx = len(self._paths)
        self.add_class("--visible")
        self.query_one(Horizontal).mount(InlineThumbnail(path=path, index=idx))
