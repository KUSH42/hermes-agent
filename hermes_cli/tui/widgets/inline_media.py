"""Inline media display widgets for the Hermes TUI.

Contains: InlineImage, InlineThumbnail, InlineImageBar,
          ChipPlan, OverflowChip, _render_attachment_thumb,
          _layout_chips, _size_suffix, _size_str_for_path.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

from rich.segment import Segment
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tooltip import TooltipMixin

_MAX_THUMBNAILS = 40

# ---------------------------------------------------------------------------
# IB-VIS-1 / IB-VIS-2: chip layout constants
# ---------------------------------------------------------------------------

_THUMB_DROP_BUDGET = 15  # drop thumbnail when per-chip width budget is below this
_MIN_CHIP_WIDTH = 14     # minimum cols for a fully-collapsed 1-row chip:
                         # 📎 (2) + 8 name chars + "  ✕" (3) + 1 padding = 14


# ---------------------------------------------------------------------------
# IB-VIS-1: shared decode helper
# ---------------------------------------------------------------------------

def _render_attachment_thumb(path: Path, cols: int = 6, rows: int = 3) -> "list[Strip]":
    """Decode path and return halfblock strips (one per output row).

    Returns [] when path cannot be decoded as an image; the caller must
    then fall back to 1-row text rendering and reset chip height to 1.

    render_halfblock signature: render_halfblock(image, max_cols, max_rows, *, ...)
    — positional for both size args, matching kitty_graphics.render_halfblock.
    """
    from hermes_cli.tui.kitty_graphics import _load_image, render_halfblock
    img = _load_image(path)
    if img is None:
        return []
    return render_halfblock(img, cols, rows)


# ---------------------------------------------------------------------------
# IB-VIS-2: ChipPlan dataclass + layout helpers
# ---------------------------------------------------------------------------

@dataclass
class ChipPlan:
    path: Path
    display_name: str   # final name to render (possibly truncated)
    show_thumb: bool    # whether to show halfblock thumbnail
    show_size: bool     # whether to append size suffix


def _layout_chips(width: int, paths: "list[Path]") -> "tuple[list[ChipPlan], int]":
    """Return (visible_plans, hidden_count).

    visible_plans: chips to render, each with budget-aware display_name,
                   show_thumb, and show_size fields set.
    hidden_count:  number of paths collapsed into the +N more chip (0 if none).
    """
    from hermes_cli.tui.widgets.status_bar import _truncate

    n = max(1, len(paths))
    budget = max(1, min(40, width // n))
    max_visible = max(1, width // _MIN_CHIP_WIDTH)

    plans: list[ChipPlan] = []
    for p in paths:
        name = p.name
        show_size = True
        show_thumb = True

        # Width-budget ladder: apply steps until chip fits within budget
        # Step 1: Drop size suffix (reclaims 8-12 cols)
        if budget - len(name) < 6:
            show_size = False

        # Step 2: Truncate name to ≤12 chars
        if len(name) > budget:
            name = _truncate(name, 12)

        # Step 3: Drop thumbnail when budget below threshold
        if budget < _THUMB_DROP_BUDGET:
            show_thumb = False

        plans.append(ChipPlan(
            path=p,
            display_name=name,
            show_thumb=show_thumb,
            show_size=show_size,
        ))

    # Chip-count overflow: collapse excess into +N more
    if len(plans) > max_visible:
        hidden_count = len(plans) - max_visible
        visible_plans = plans[:max_visible]
        return visible_plans, hidden_count

    return plans, 0


# ---------------------------------------------------------------------------
# IB-VIS-3: size suffix helpers
# ---------------------------------------------------------------------------

def _size_suffix(path: Path, budget_spare: int) -> str:
    """Return ' (N KB)' when spare budget >= 6; '' otherwise or on stat error."""
    if budget_spare < 6:
        return ""
    try:
        from hermes_cli.tui.streaming_microcopy import _human_size
        return f" ({_human_size(path.stat().st_size)})"
    except OSError:
        return ""


def _size_str_for_path(path: Path) -> str:
    """Return human-readable size string for path, or '' on OSError."""
    try:
        from hermes_cli.tui.streaming_microcopy import _human_size
        return _human_size(path.stat().st_size)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# IB-VIS-2: OverflowChip
# ---------------------------------------------------------------------------

class OverflowChip(Static):
    """Simple 1-row chip showing +N more when attachments exceed visible budget."""

    DEFAULT_CSS = """
    OverflowChip {
        width: auto;
        height: 1;
        color: $text-muted;
        margin: 0 1;
    }
    """


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
        self._last_resize_size: tuple[int, int] = (-1, -1)

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
            _log.debug("InlineMedia image load failed", exc_info=True)
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
            _log.debug("InlineMedia video load failed", exc_info=True)

    def on_unmount(self) -> None:
        from hermes_cli.tui.kitty_graphics import _get_renderer
        if self._image_id is not None:
            self._emit_raw(_get_renderer().delete_sequence(self._image_id))
            self._image_id = None

    def on_resize(self, event: "events.Resize") -> None:
        # Use _reactive_image (internal backing attr) to avoid ReactiveError
        # when on_resize fires before the widget is fully mounted.
        img = self._reactive_image  # type: ignore[attr-defined]
        if img is None:
            return
        new_size = (event.size.width, event.size.height)
        if new_size == self._last_resize_size:
            return
        self._last_resize_size = new_size
        self.watch_image(img)


class _OldnessChip(Static):
    """Small chip at the left of InlineImageBar showing pruned image count."""

    DEFAULT_CSS = """
    _OldnessChip {
        width: auto;
        height: 1;
        color: $text-muted;
        margin: 0 1;
    }
    """


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
        cwd = Path(getattr(self.app, "get_working_directory", lambda: Path.cwd())())
        p = Path(self._path)
        try:
            rel = p.relative_to(cwd)
            self._tooltip_text = rel.as_posix()
        except ValueError:
            self._tooltip_text = p.as_posix()
        self._load_strips()

    @work(thread=True)
    def _load_strips(self) -> None:
        try:
            from hermes_cli.tui.kitty_graphics import _load_image, render_halfblock
            img = _load_image(self._path)
            if img is not None:
                strips = render_halfblock(img, max_cols=10, max_rows=6)
            else:
                strips = []
            self.app.call_from_thread(self._apply_strips, strips)
        except Exception:
            _log.exception("inline_media._load_strips: image load failed")

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
        self._chips_by_key: dict[tuple[str, int], InlineThumbnail] = {}
        self._chip_order: list[tuple[str, int]] = []
        self._evicted_count: int = 0
        self._next_idx: int = 0
        # _paths kept for backwards-compat attribute access; not used for cap logic.
        self._paths: list[str] = []
        self._enabled: bool = True

    def compose(self) -> ComposeResult:
        yield Horizontal()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_index(self) -> int:
        """Return a monotonically increasing stable ID regardless of evictions."""
        idx = self._next_idx
        self._next_idx += 1
        return idx

    def _dedupe_key(self, path: str) -> tuple[str, int]:
        p = Path(path).resolve()
        try:
            mtime = int(p.stat().st_mtime)
        except OSError:
            mtime = 0
        return (str(p), mtime)

    def _highlight_existing(self, key: tuple[str, int]) -> None:
        """Pulse the existing chip for the given key (dedupe hit)."""
        chip = self._chips_by_key.get(key)
        if chip is None:
            return
        chip.add_class("--highlight-pulse")
        self.set_timer(0.6, lambda: chip.remove_class("--highlight-pulse"))

    def _evict_oldest(self, container: Horizontal) -> None:
        """Remove the oldest chip from the DOM and tracking structures."""
        if not self._chip_order:
            return
        oldest_key = self._chip_order.pop(0)
        chip = self._chips_by_key.pop(oldest_key, None)
        if chip is not None:
            chip.remove()
        self._evicted_count += 1

    def _sync_oldness_chip(self, container: Horizontal) -> None:
        """Mount or update the +M earlier images chip at the left of the bar.

        If _evicted_count == 0, remove any existing chip. Otherwise, mount
        one the first time and update its label and tooltip on subsequent calls.
        """
        existing = list(container.query(_OldnessChip))
        if self._evicted_count == 0:
            for c in existing:
                c.remove()
            return
        label = f"+{self._evicted_count} earlier images"
        tip = f"{self._evicted_count} images pruned from the start of the bar"
        if existing:
            existing[0].update(label)
            existing[0].tooltip = tip
        else:
            chip = _OldnessChip(label)
            chip.tooltip = tip
            container.mount(
                chip,
                before=container.children[0] if container.children else None,
            )

    def _recompute_visibility(self) -> None:
        """Add or remove --visible based on whether any chips are mounted."""
        has_chips = bool(self._chips_by_key)
        if has_chips:
            self.add_class("--visible")
        else:
            self.remove_class("--visible")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_image(self, path: str) -> None:
        """Add a thumbnail. No-op when display.image_bar is disabled."""
        if not self._enabled:
            return
        key = self._dedupe_key(path)
        if key in self._chips_by_key:
            self._highlight_existing(key)
            return
        self._paths.append(path)
        container = self.query_one(Horizontal)
        if len(self._chips_by_key) >= _MAX_THUMBNAILS:
            self._evict_oldest(container)
        chip = InlineThumbnail(path=path, index=self._next_index())
        self._chips_by_key[key] = chip
        self._chip_order.append(key)
        container.mount(chip)
        self._sync_oldness_chip(container)
        self._recompute_visibility()

    def clear(self) -> None:
        """Remove all thumbnails and reset tracking state."""
        container = self.query_one(Horizontal)
        for chip in list(container.query(InlineThumbnail)):
            chip.remove()
        for chip in list(container.query(_OldnessChip)):
            chip.remove()
        self._chips_by_key.clear()
        self._chip_order.clear()
        self._evicted_count = 0
        self._paths.clear()
        self._recompute_visibility()
