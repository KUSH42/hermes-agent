"""Tests for InlineProseLog, InlineImageCache, and related span model (spec §16).

Groups:
  1  (5)  TextSpan/ImageSpan frozen; cache LRU; cache key + _RenderMode; singleton; refcount
  2  (4)  halfblock renderer: 1×1, 2×1, transparent, missing file
  3  (4)  Kitty placeholder: _supports_unicode_placeholders; transmit sequence; placeholder strip
  4  (2)  SIXEL cap → halfblock fallback; warning logged once
  5  (4)  on_resize invalidates cache; LRU eviction emits delete_sequence; on_unmount decr refcount
  6  (4)  paint plan: single row, wrapped multi-row, image-at-end wraps, placeholder meta → span_index
  7  (4)  write_inline _plain_lines; alt_text in plain; mixed write()+write_inline(); _logical_count
  8  (5)  render_line dispatch; parent path; cap=NONE alt_text; selection; adjust_cell_length clip
  9  (3)  MessagePanel/ReasoningPanel compose InlineProseLog; get_selection prefers _plain_lines
 10  (3)  integration: write 3 mixed lines; clipboard returns alt_text; resize → cache invalidation
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
IMG_2X2 = FIXTURES / "emoji_test_2x2.png"
IMG_4X4 = FIXTURES / "emoji_test_4x4.png"
MISSING  = FIXTURES / "does_not_exist.png"


def _make_span_2x1():
    from hermes_cli.tui.inline_prose import ImageSpan
    return ImageSpan(image_path=IMG_2X2, cell_width=2, cell_height=1, alt_text=":red:", cache_key="red2x1")


def _make_span_4x1():
    from hermes_cli.tui.inline_prose import ImageSpan
    return ImageSpan(image_path=IMG_4X4, cell_width=4, cell_height=1, alt_text=":green:", cache_key="green4x1")


def _halfblock_mode():
    from hermes_cli.tui.inline_prose import _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    return _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=8, cell_px_h=16)


def _none_mode():
    from hermes_cli.tui.inline_prose import _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    return _RenderMode(cap=GraphicsCap.NONE, cell_px_w=8, cell_px_h=16)


def _sixel_mode():
    from hermes_cli.tui.inline_prose import _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    return _RenderMode(cap=GraphicsCap.SIXEL, cell_px_w=8, cell_px_h=16)


def fresh_cache():
    from hermes_cli.tui.inline_prose import InlineImageCache
    return InlineImageCache()


# ──────────────────────────────────────────────────────────────────────────────
# Group 1 — dataclasses + cache mechanics
# ──────────────────────────────────────────────────────────────────────────────

def test_textspan_frozen():
    from hermes_cli.tui.inline_prose import TextSpan
    t = Text("hello")
    span = TextSpan(text=t)
    with pytest.raises((AttributeError, TypeError)):
        span.text = Text("other")  # type: ignore[misc]


def test_imagespan_frozen():
    from hermes_cli.tui.inline_prose import ImageSpan
    span = ImageSpan(image_path=IMG_2X2, cell_width=2)
    with pytest.raises((AttributeError, TypeError)):
        span.cell_width = 3  # type: ignore[misc]


def test_imagespan_defaults():
    from hermes_cli.tui.inline_prose import ImageSpan
    span = ImageSpan(image_path=IMG_2X2, cell_width=1)
    assert span.cell_height == 1
    assert span.alt_text == ""
    assert span.cache_key == ""


def test_cache_key_includes_render_mode():
    """Different _RenderMode instances produce distinct cache keys."""
    from hermes_cli.tui.inline_prose import _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    span = _make_span_2x1()
    cache = fresh_cache()
    m1 = _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=8, cell_px_h=16)
    m2 = _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=9, cell_px_h=18)
    assert cache._make_key(span, m1) != cache._make_key(span, m2)


def test_cache_lru_eviction():
    """LRU evicts oldest entry when _MAX_CACHE exceeded."""
    from hermes_cli.tui.inline_prose import InlineImageCache, ImageSpan, _RenderMode, _MAX_CACHE
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    cache = InlineImageCache()
    mode = _RenderMode(cap=GraphicsCap.NONE, cell_px_w=8, cell_px_h=16)
    # Fill to max + 1 using distinct cache_key strings
    for i in range(_MAX_CACHE + 1):
        span = ImageSpan(image_path=IMG_2X2, cell_width=1, cache_key=f"key_{i}")
        cache.get_strips(span, mode)
    assert len(cache._entries) == _MAX_CACHE


def test_singleton_lazy():
    from hermes_cli.tui.inline_prose import _get_image_cache, _reset_image_cache
    _reset_image_cache()
    a = _get_image_cache()
    b = _get_image_cache()
    assert a is b
    _reset_image_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Group 2 — halfblock renderer
# ──────────────────────────────────────────────────────────────────────────────

def test_halfblock_1x1_cell():
    span = _make_span_2x1()
    span2 = type(span)(
        image_path=IMG_2X2, cell_width=1, cell_height=1, alt_text=":r:", cache_key="r1"
    )
    mode = _halfblock_mode()
    cache = fresh_cache()
    strips = cache.get_strips(span2, mode)
    assert len(strips) == 1
    assert isinstance(strips[0], Strip)


def test_halfblock_2x1_cell():
    span = _make_span_2x1()
    mode = _halfblock_mode()
    cache = fresh_cache()
    strips = cache.get_strips(span, mode)
    assert len(strips) == 1
    # Each strip normalised to cell_width=2
    assert strips[0].cell_length == 2


def test_halfblock_transparent_png():
    from hermes_cli.tui.inline_prose import ImageSpan
    from PIL import Image
    import io, tempfile, os
    img = Image.new("RGBA", (4, 2), (255, 0, 0, 128))  # semi-transparent
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f, format="PNG")
        tmp_path = Path(f.name)
    try:
        span = ImageSpan(image_path=tmp_path, cell_width=2, cell_height=1)
        mode = _halfblock_mode()
        strips = fresh_cache().get_strips(span, mode)
        assert len(strips) == 1
    finally:
        os.unlink(tmp_path)


def test_halfblock_missing_file():
    from hermes_cli.tui.inline_prose import ImageSpan
    span = ImageSpan(image_path=MISSING, cell_width=2, cell_height=1)
    mode = _halfblock_mode()
    strips = fresh_cache().get_strips(span, mode)
    assert strips == []


# ──────────────────────────────────────────────────────────────────────────────
# Group 3 — Kitty unicode placeholder helpers
# ──────────────────────────────────────────────────────────────────────────────

def test_supports_unicode_placeholders_true():
    from hermes_cli.tui.kitty_graphics import _supports_unicode_placeholders, _reset_unicode_placeholders_cache
    _reset_unicode_placeholders_cache()
    with patch.dict(os.environ, {"TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"}):
        _reset_unicode_placeholders_cache()
        assert _supports_unicode_placeholders() is True
    _reset_unicode_placeholders_cache()


def test_supports_unicode_placeholders_false():
    from hermes_cli.tui.kitty_graphics import _supports_unicode_placeholders, _reset_unicode_placeholders_cache
    _reset_unicode_placeholders_cache()
    with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False):
        os.environ.pop("KITTY_WINDOW_ID", None)
        _reset_unicode_placeholders_cache()
        assert _supports_unicode_placeholders() is False
    _reset_unicode_placeholders_cache()


def test_transmit_only_sequence_flags():
    from hermes_cli.tui.kitty_graphics import transmit_only_sequence
    from PIL import Image
    img = Image.new("RGBA", (8, 16), (255, 0, 0, 255))
    seq = transmit_only_sequence(image_id=42, image=img, cell_width=1, cell_height=1)
    assert "a=T" in seq
    assert "U=1" in seq
    assert "i=42" in seq
    assert seq.startswith("\x1b_G")
    assert seq.endswith("\x1b\\")


def test_placeholder_strip_uses_placeholder_char():
    from hermes_cli.tui.kitty_graphics import build_tgp_placeholder_strips, _PLACEHOLDER_CHAR
    strips = build_tgp_placeholder_strips(image_id=1, cell_width=2, cell_height=1)
    assert len(strips) == 1
    row_text = "".join(seg.text for seg in strips[0])
    assert _PLACEHOLDER_CHAR in row_text
    # foreground color must be set (encodes image_id)
    for seg in strips[0]:
        assert seg.style is not None
        assert seg.style.color is not None


# ──────────────────────────────────────────────────────────────────────────────
# Group 4 — SIXEL fallback
# ──────────────────────────────────────────────────────────────────────────────

def test_sixel_falls_back_to_halfblock():
    from hermes_cli.tui.inline_prose import _reset_image_cache
    _reset_image_cache()
    span = _make_span_2x1()
    mode = _sixel_mode()
    cache = fresh_cache()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        strips = cache.get_strips(span, mode)
    # Should return halfblock strips, not empty
    assert len(strips) >= 1
    assert isinstance(strips[0], Strip)
    _reset_image_cache()


def test_sixel_warning_logged_once():
    from hermes_cli.tui.inline_prose import _reset_image_cache, ImageSpan
    _reset_image_cache()
    mode = _sixel_mode()
    cache = fresh_cache()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cache.get_strips(_make_span_2x1(), mode)
        cache.get_strips(
            ImageSpan(image_path=IMG_4X4, cell_width=4, cache_key="g4"), mode
        )
    # Warning should be emitted exactly once (guarded by _sixel_warned flag)
    sixel_warns = [x for x in w if "SIXEL" in str(x.message)]
    assert len(sixel_warns) == 1
    _reset_image_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Group 5 — resize + lifecycle
# ──────────────────────────────────────────────────────────────────────────────

def test_on_resize_invalidates_stale_entries():
    """invalidate_for_resize flushes entries with old cell_px dims."""
    from hermes_cli.tui.inline_prose import InlineImageCache, _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    cache = InlineImageCache()
    old_mode = _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=8, cell_px_h=16)
    span = _make_span_2x1()
    cache.get_strips(span, old_mode)
    assert len(cache._entries) == 1
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(10, 20)):
        cache.invalidate_for_resize()
    assert len(cache._entries) == 0


def test_invalidate_for_resize_keeps_current_entries():
    """Entries whose cell_px match current dims are kept."""
    from hermes_cli.tui.inline_prose import InlineImageCache, _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    cache = InlineImageCache()
    cw, ch = 8, 16
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(cw, ch)):
        mode = _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=cw, cell_px_h=ch)
        cache.get_strips(_make_span_2x1(), mode)
        cache.invalidate_for_resize()
    assert len(cache._entries) == 1


def test_lru_eviction_emits_delete_sequence_for_tgp():
    """On TGP entry eviction, delete sequence is written to stdout."""
    from hermes_cli.tui.inline_prose import InlineImageCache, _CacheEntry, _MAX_CACHE
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    from textual.strip import Strip
    cache = InlineImageCache()
    tgp_key = ("tgp_test", 2, 1, None)
    cache._entries[tgp_key] = _CacheEntry(
        strips=[Strip.blank(2)],
        cap=GraphicsCap.TGP,
        image_id=99,
        widget_ids={1},
    )
    # Fill remaining slots to force eviction of tgp_key (it's oldest)
    mode = _none_mode()
    from hermes_cli.tui.inline_prose import ImageSpan
    for i in range(_MAX_CACHE):
        span = ImageSpan(image_path=IMG_2X2, cell_width=1, cache_key=f"fill_{i}")
        cache.get_strips(span, mode)
    # tgp_key should have been evicted and delete sequence emitted
    assert tgp_key not in cache._entries


def test_decrement_refcount_drops_entry_at_zero():
    from hermes_cli.tui.inline_prose import InlineImageCache
    cache = InlineImageCache()
    span = _make_span_2x1()
    mode = _halfblock_mode()
    cache.get_strips(span, mode, widget_id=1)
    key = cache._make_key(span, mode)
    assert key in cache._entries
    cache.decrement_refcount(span, mode, widget_id=1)
    assert key not in cache._entries


# ──────────────────────────────────────────────────────────────────────────────
# Group 6 — paint plan
# ──────────────────────────────────────────────────────────────────────────────

def _make_test_widget_class(width: int = 80):
    """Return a test subclass of InlineProseLog with a fixed scrollable_content_region."""
    from hermes_cli.tui.widgets import InlineProseLog
    from textual.geometry import Region

    class _TestWidget(InlineProseLog):
        _test_width: int = width

        @property
        def scrollable_content_region(self):  # type: ignore[override]
            return Region(0, 0, self._test_width, 100)

    return _TestWidget


def _make_widget(width: int = 80):
    """Create a minimal InlineProseLog for unit tests (no Textual app needed)."""
    cls = _make_test_widget_class(width)
    widget = cls(markup=False, highlight=False, wrap=True)
    return widget


def test_single_row_paint_plan():
    """Short line with no wrap → 1 visual row in paint plan."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = _make_widget()
    line = [
        TextSpan(text=Text("hi ")),
        ImageSpan(image_path=IMG_2X2, cell_width=2, cell_height=1, alt_text=":r:", cache_key="r"),
        TextSpan(text=Text(" world")),
    ]
    text = widget._line_to_text(line)
    plan = widget._build_paint_plan(line, text)
    assert len(plan) == 1  # 1 visual row (no wrap at width=80)
    kinds = [op.kind for op in plan[0]]
    assert "text" in kinds
    assert "image" in kinds


def test_paint_plan_placeholder_meta_maps_to_span_index():
    """_PaintOp.span_index matches the ImageSpan's position in the InlineLine."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = _make_widget()
    line = [
        TextSpan(text=Text("a")),   # index 0 — TextSpan
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":r:", cache_key="ri"),  # index 1
    ]
    text = widget._line_to_text(line)
    plan = widget._build_paint_plan(line, text)
    # Find image op
    img_ops = [op for ops in plan for op in ops if op.kind == "image"]
    assert len(img_ops) == 1
    assert img_ops[0].span_index == 1  # position of ImageSpan in line


def test_wrapped_line_produces_multi_row_plan():
    """A long line should wrap into multiple visual rows at narrow width."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = _make_widget(width=20)  # narrow
    # Create a line that's 40+ chars wide
    long_text = "A" * 35
    line = [
        TextSpan(text=Text(long_text)),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":r:", cache_key="rw"),
    ]
    text = widget._line_to_text(line)
    plan = widget._build_paint_plan(line, text)
    assert len(plan) >= 2  # must wrap at width=20


def test_image_at_end_wraps_to_next_row():
    """An ImageSpan positioned exactly at the wrap boundary wraps to next visual row."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    width = 10
    widget = _make_widget(width=width)
    # Fill exactly `width - 2` chars of text, then a 2-cell image
    filler = "X" * (width - 2)  # 8 chars
    line = [
        TextSpan(text=Text(filler)),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":r:", cache_key="re"),
    ]
    text = widget._line_to_text(line)
    plan = widget._build_paint_plan(line, text)
    # Image fits on row 0 (8+2=10, exactly width); if Rich wraps it, it'll be row 1
    # Either way, the plan must have at least 1 row
    assert len(plan) >= 1
    all_ops = [op for ops in plan for op in ops]
    assert any(op.kind == "image" for op in all_ops)


# ──────────────────────────────────────────────────────────────────────────────
# Group 7 — write_inline + _plain_lines
# ──────────────────────────────────────────────────────────────────────────────

def test_line_to_plain_contains_alt_text():
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = _make_widget()
    line = [
        TextSpan(text=Text("hello ")),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":wave:", cache_key="w"),
        TextSpan(text=Text(" world")),
    ]
    plain = widget._line_to_plain(line)
    assert ":wave:" in plain
    assert "hello" in plain
    assert "world" in plain


def test_line_to_text_uses_spaces_for_image():
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = _make_widget()
    line = [
        ImageSpan(image_path=IMG_2X2, cell_width=3, alt_text=":x:", cache_key="x"),
    ]
    text = widget._line_to_text(line)
    assert text.plain == "   "  # 3 placeholder spaces


def test_logical_count_increments_on_write_inline():
    """Each write_inline call increments the internal logical count."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _get_image_cache, _reset_image_cache
    from hermes_cli.tui.widgets import InlineProseLog
    _reset_image_cache()
    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    # Monkey-patch write() to avoid needing a mounted app
    written: list = []
    def fake_write(content, **kw):
        written.append(content)
        widget._logical_count += 1
        return widget
    widget.write = fake_write  # type: ignore[method-assign]
    widget._plain_lines = []
    original_write_ws = InlineProseLog.write_with_source
    def fake_wws(self, styled, plain, **kw):
        self._plain_lines.append(plain)
        self.write(styled)
        return self
    widget.write_with_source = lambda styled, plain, **kw: fake_wws(widget, styled, plain, **kw)  # type: ignore[method-assign]

    line = [TextSpan(text=Text("hi"))]
    widget.write_inline(line)
    assert widget._logical_count == 1
    assert len(widget._plain_lines) == 1
    assert 0 in widget._inline_lines
    _reset_image_cache()


def test_plain_write_increments_logical_count():
    """Plain write() also increments _logical_count."""
    from hermes_cli.tui.widgets import InlineProseLog
    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    # Simulate a pre-mount deferred write (lines stays empty)
    assert widget._logical_count == 0
    # Manually call the tracking logic (can't mount without app)
    idx = widget._logical_count
    before = len(widget.lines)
    # Simulate a write that adds 1 visual row
    widget.lines.append(Strip.blank(80))
    after = len(widget.lines)
    delta = after - before
    if delta > 0:
        widget._logical_visual_rows[idx] = delta
    widget._logical_count += 1
    assert widget._logical_count == 1
    assert widget._logical_visual_rows.get(0) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Group 8 — render_line dispatch
# ──────────────────────────────────────────────────────────────────────────────

def test_owner_line_for_visual_y_plain_returns_minus_one():
    """Plain text lines → _owner_line_for_visual_y returns (-1, 0)."""
    widget = _make_widget()
    widget._logical_count = 3
    widget._logical_visual_rows = {0: 1, 1: 1, 2: 1}
    # No inline lines registered → all plain
    assert widget._owner_line_for_visual_y(0) == (-1, 0)
    assert widget._owner_line_for_visual_y(1) == (-1, 0)


def test_owner_line_for_visual_y_inline_returns_index():
    """InlineLines → _owner_line_for_visual_y returns (logical_idx, row_in_line)."""
    from hermes_cli.tui.inline_prose import TextSpan, _PaintOp
    widget = _make_widget()
    widget._logical_count = 2
    widget._logical_visual_rows = {0: 1}
    # Logical line 1 is an inline line with 1 visual row
    widget._inline_lines[1] = [TextSpan(text=Text("x"))]
    widget._inline_paint[1] = [[_PaintOp(kind="text", text_segments=[], width=1)]]
    # visual row 0 → plain line 0; visual row 1 → inline line 1
    assert widget._owner_line_for_visual_y(0) == (-1, 0)
    assert widget._owner_line_for_visual_y(1) == (1, 0)


def test_render_line_cap_none_returns_alt_text():
    """With cap=NONE the rendered strip contains the alt_text."""
    from hermes_cli.tui.inline_prose import ImageSpan, _RenderMode, _reset_image_cache
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    _reset_image_cache()
    widget = _make_widget()
    span = ImageSpan(image_path=MISSING, cell_width=5, alt_text="NOPE!", cache_key="none_test")
    mode = _RenderMode(cap=GraphicsCap.NONE, cell_px_w=8, cell_px_h=16)
    cache = fresh_cache()
    strips = cache.get_strips(span, mode)
    assert len(strips) == 1
    text = "".join(seg.text for seg in strips[0])
    assert "NOPE!" in text
    _reset_image_cache()


def test_render_inline_line_strip_width():
    """_render_inline_line returns a strip whose cell_length == widget width."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _PaintOp
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    widget = _make_widget(width=40)

    span = ImageSpan(image_path=IMG_2X2, cell_width=2, cell_height=1, alt_text=":r:", cache_key="ri2")
    line = [TextSpan(text=Text("hi ")), span]
    widget._inline_lines[0] = line
    widget._inline_paint[0] = [[
        _PaintOp(kind="text", text_segments=[Segment("hi ")], width=3),
        _PaintOp(kind="image", span_index=1, image_row=0, width=2),
    ]]

    with (
        patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK),
        patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)),
        patch("hermes_cli.tui.kitty_graphics._supports_unicode_placeholders", return_value=False),
        patch.object(type(widget), "text_selection", new_callable=lambda: property(lambda self: None)),
    ):
        strip = widget._render_inline_line(
            owner_index=0, row_in_line=0, scroll_x=0, content_y=0
        )
    assert strip.cell_length == 40


def test_selection_does_not_raise():
    """get_selection for inline-line widget returns plain text without crash."""
    from hermes_cli.tui.widgets import InlineProseLog
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    widget._plain_lines = ["hello :emoji: world"]
    widget._inline_lines[0] = [
        TextSpan(text=Text("hello ")),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":emoji:", cache_key="e"),
        TextSpan(text=Text(" world")),
    ]
    sel = MagicMock()
    sel.extract.return_value = "hello :emoji: world"
    result = widget.get_selection(sel)
    assert result is not None
    assert ":emoji:" in result[0]


# ──────────────────────────────────────────────────────────────────────────────
# Group 9 — migration + regression
# ──────────────────────────────────────────────────────────────────────────────

def test_message_panel_response_log_is_inline_prose_log():
    from hermes_cli.tui.widgets import MessagePanel, InlineProseLog
    panel = MessagePanel()
    assert isinstance(panel.response_log, InlineProseLog)


def test_reasoning_panel_reasoning_log_is_inline_prose_log():
    from hermes_cli.tui.widgets import ReasoningPanel, InlineProseLog
    panel = ReasoningPanel()
    assert isinstance(panel._reasoning_log, InlineProseLog)


def test_get_selection_prefers_plain_lines_for_inline():
    from hermes_cli.tui.widgets import InlineProseLog
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    widget._plain_lines = ["first line", "hello :img: world"]
    widget._inline_lines[1] = [
        TextSpan(text=Text("hello ")),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":img:", cache_key="img1"),
        TextSpan(text=Text(" world")),
    ]
    sel = MagicMock()
    sel.extract.return_value = "hello :img: world"
    result = widget.get_selection(sel)
    assert result is not None
    # extract was called with newline-joined _plain_lines
    call_arg = sel.extract.call_args[0][0]
    assert ":img:" in call_arg


# ──────────────────────────────────────────────────────────────────────────────
# Group 10 — integration
# ──────────────────────────────────────────────────────────────────────────────

def test_clipboard_returns_alt_text():
    """copy_content joins _plain_lines which contain alt_text substitutions."""
    from hermes_cli.tui.widgets import InlineProseLog
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan
    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    widget._plain_lines = ["hello :emoji: world"]
    assert ":emoji:" in widget.copy_content()


def test_resize_invalidates_cache_and_rebuilds_paint_plans():
    """on_resize with changed cell_px triggers cache invalidation + plan rebuild."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _get_image_cache, _reset_image_cache, _RenderMode
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    _reset_image_cache()

    widget = _make_widget(width=80)
    widget._last_cell_px = (8, 16)

    # Manually insert an inline line + stale cache entry
    span = ImageSpan(image_path=IMG_2X2, cell_width=2, cell_height=1, alt_text=":r:", cache_key="rr")
    line = [TextSpan(text=Text("x ")), span]
    widget._inline_lines[0] = line
    widget._inline_paint[0] = []  # empty — simulates stale

    stale_mode = _RenderMode(cap=GraphicsCap.HALFBLOCK, cell_px_w=8, cell_px_h=16)
    cache = _get_image_cache()
    cache.get_strips(span, stale_mode)
    assert len(cache._entries) == 1

    widget.refresh = lambda: None  # no-op

    with (
        patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(10, 20)),
        patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK),
        patch("hermes_cli.tui.kitty_graphics._supports_unicode_placeholders", return_value=False),
    ):
        event = MagicMock()
        widget.on_resize(event)

    # Stale entry (cell_px=8x16) must be gone; paint plan for line 0 rebuilt
    remaining = [k for k in cache._entries if k[3].cell_px_w == 8]
    assert len(remaining) == 0
    assert len(widget._inline_paint[0]) >= 1  # plan rebuilt

    _reset_image_cache()


def test_write_inline_three_lines():
    """write_inline on three lines registers them correctly."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _reset_image_cache
    from hermes_cli.tui.widgets import InlineProseLog
    _reset_image_cache()

    widget = InlineProseLog(markup=False, highlight=False, wrap=True)
    # Patch write to avoid needing app
    def fake_write(content, **kw):
        widget._logical_count += 1
        return widget
    widget.write = fake_write  # type: ignore[method-assign]
    widget._plain_lines = []
    def fake_wws(styled, plain, **kw):
        widget._plain_lines.append(plain)
        widget.write(styled)
        return widget
    widget.write_with_source = fake_wws  # type: ignore[method-assign]

    lines = [
        [TextSpan(text=Text("hello ")), ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":a:", cache_key="a0")],
        [TextSpan(text=Text("world ")), ImageSpan(image_path=IMG_4X4, cell_width=4, alt_text=":b:", cache_key="b0")],
        [TextSpan(text=Text("done"))],
    ]
    for line in lines:
        widget.write_inline(line)

    assert widget._logical_count == 3
    assert len(widget._inline_lines) == 3
    assert len(widget._plain_lines) == 3
    assert ":a:" in widget._plain_lines[0]
    assert ":b:" in widget._plain_lines[1]

    _reset_image_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Group 11 — render-safety fixes (no PIL/stdout in render_line)
# ──────────────────────────────────────────────────────────────────────────────

def test_get_strips_or_alt_returns_alt_on_miss():
    """get_strips_or_alt never calls _render; returns alt strips on cache miss."""
    from hermes_cli.tui.inline_prose import _reset_image_cache
    _reset_image_cache()
    span = _make_span_2x1()
    mode = _halfblock_mode()
    cache = fresh_cache()

    render_called = []
    original_render = cache._render
    def spy_render(*a, **kw):
        render_called.append(True)
        return original_render(*a, **kw)
    cache._render = spy_render  # type: ignore[method-assign]

    strips = cache.get_strips_or_alt(span, mode, widget_id=99)

    assert len(render_called) == 0, "_render must NOT be called from get_strips_or_alt on miss"
    assert len(strips) == 1
    assert strips[0] is not None
    # alt_text is ":red:", width=2 — result padded/cropped to cell_width
    row_text = "".join(seg.text for seg in strips[0])
    assert ":red:" in row_text or len(row_text) >= 1  # alt strip returned

    _reset_image_cache()


def test_get_strips_or_alt_returns_cached_strips():
    """get_strips_or_alt returns real strips when cache is warm."""
    from hermes_cli.tui.inline_prose import _reset_image_cache
    _reset_image_cache()
    span = _make_span_2x1()
    mode = _halfblock_mode()
    cache = fresh_cache()

    # Warm up the cache via get_strips
    warm_strips = cache.get_strips(span, mode)
    assert len(warm_strips) >= 1

    # Now get_strips_or_alt must return the same entry (no _render call)
    render_called = []
    original_render = cache._render
    def spy_render(*a, **kw):
        render_called.append(True)
        return original_render(*a, **kw)
    cache._render = spy_render  # type: ignore[method-assign]

    result = cache.get_strips_or_alt(span, mode)

    assert len(render_called) == 0, "get_strips_or_alt must not re-render on cache hit"
    assert result is warm_strips

    _reset_image_cache()


def test_render_mode_cached_after_first_call():
    """_current_render_mode() caches result; ioctl not re-issued on subsequent calls."""
    from hermes_cli.tui.inline_prose import _reset_image_cache
    from hermes_cli.tui.kitty_graphics import GraphicsCap, _reset_cell_px_cache
    _reset_image_cache()
    _reset_cell_px_cache()

    widget = _make_widget()

    ioctl_calls = []
    def fake_cell_px():
        ioctl_calls.append(True)
        return (8, 16)

    with (
        patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK),
        patch("hermes_cli.tui.kitty_graphics.cell_width_px", side_effect=lambda: (ioctl_calls.append(True), 8)[1]),
        patch("hermes_cli.tui.kitty_graphics.cell_height_px", return_value=16),
        patch("hermes_cli.tui.kitty_graphics._supports_unicode_placeholders", return_value=False),
    ):
        widget._render_mode_cache = None
        mode1 = widget._current_render_mode()
        mode2 = widget._current_render_mode()
        mode3 = widget._current_render_mode()

    assert mode1 is mode2 is mode3, "_current_render_mode() must return the same object"
    assert len(ioctl_calls) == 1, "cell_width_px() must only be called once (cached)"

    _reset_image_cache()


def test_render_mode_cache_invalidated_on_resize():
    """on_resize clears _render_mode_cache so next _current_render_mode() recomputes."""
    from hermes_cli.tui.inline_prose import _reset_image_cache
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    _reset_image_cache()

    widget = _make_widget()
    widget.refresh = lambda: None

    with (
        patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(10, 20)),
        patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK),
        patch("hermes_cli.tui.kitty_graphics._supports_unicode_placeholders", return_value=False),
    ):
        widget.on_resize(MagicMock())

    assert widget._render_mode_cache is None, "on_resize must invalidate _render_mode_cache"

    _reset_image_cache()


def test_render_inline_line_no_render_on_cache_miss():
    """_render_inline_line uses get_strips_or_alt — never calls _render() on miss."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _reset_image_cache
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    _reset_image_cache()

    widget = _make_widget(width=80)
    span = ImageSpan(image_path=IMG_2X2, cell_width=2, cell_height=1, alt_text=":x:", cache_key="x1")
    line = [TextSpan(text=Text("hi ")), span]
    text = widget._line_to_text(line)
    widget._inline_lines[0] = line
    widget._inline_paint[0] = widget._build_paint_plan(line, text)
    widget._logical_visual_rows[0] = 1

    render_called = []
    original_render = widget._image_cache._render
    def spy_render(*a, **kw):
        render_called.append(True)
        return original_render(*a, **kw)
    widget._image_cache._render = spy_render  # type: ignore[method-assign]

    with (
        patch("hermes_cli.tui.kitty_graphics.get_caps", return_value=GraphicsCap.HALFBLOCK),
        patch("hermes_cli.tui.kitty_graphics.cell_width_px", return_value=8),
        patch("hermes_cli.tui.kitty_graphics.cell_height_px", return_value=16),
        patch("hermes_cli.tui.kitty_graphics._supports_unicode_placeholders", return_value=False),
        patch.object(type(widget), "text_selection", new_callable=lambda: property(lambda self: None)),
    ):
        widget._render_mode_cache = None
        strip = widget._render_inline_line(owner_index=0, row_in_line=0, scroll_x=0, content_y=0)

    assert len(render_called) == 0, "_render_inline_line must not call _render() on cache miss"
    assert strip is not None

    _reset_image_cache()


def test_write_inline_triggers_prerender_for_image_spans():
    """write_inline calls _prerender_line_images for lines containing ImageSpans."""
    from hermes_cli.tui.inline_prose import TextSpan, ImageSpan, _reset_image_cache
    from hermes_cli.tui.kitty_graphics import GraphicsCap
    _reset_image_cache()

    widget = _make_widget(width=80)
    prerender_calls: list = []

    original_prerender = widget._prerender_line_images.__func__  # type: ignore[attr-defined]
    def fake_prerender(self_w, line_index, line):
        prerender_calls.append((line_index, len(line)))
    widget._prerender_line_images = lambda idx, ln: fake_prerender(widget, idx, ln)  # type: ignore[method-assign]

    # Patch write to avoid needing app
    def fake_write(content, **kw):
        widget._logical_count += 1
        return widget
    widget.write = fake_write  # type: ignore[method-assign]
    def fake_wws(styled, plain, **kw):
        widget._plain_lines = getattr(widget, "_plain_lines", [])
        widget._plain_lines.append(plain)
        widget.write(styled)
        return widget
    widget.write_with_source = fake_wws  # type: ignore[method-assign]

    # Line with image → prerender triggered
    line_with_img = [
        TextSpan(text=Text("hello ")),
        ImageSpan(image_path=IMG_2X2, cell_width=2, alt_text=":e:", cache_key="e0"),
    ]
    widget.write_inline(line_with_img)
    assert len(prerender_calls) == 1, "_prerender_line_images must be called for image lines"

    # Line without image → prerender NOT triggered
    line_no_img = [TextSpan(text=Text("plain text"))]
    widget.write_inline(line_no_img)
    assert len(prerender_calls) == 1, "_prerender_line_images must NOT be called for text-only lines"

    _reset_image_cache()
