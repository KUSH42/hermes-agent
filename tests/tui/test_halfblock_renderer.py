"""Tests for render_halfblock() in hermes_cli.tui.kitty_graphics."""

from __future__ import annotations

import pytest

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")

from textual.strip import Strip


@pytest.fixture(autouse=True)
def reset_caps(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    yield
    from hermes_cli.tui.kitty_graphics import _reset_caps
    _reset_caps()


def _solid(color: tuple[int, int, int], w: int = 4, h: int = 4) -> PILImage.Image:
    return PILImage.new("RGB", (w, h), color=color)


def _half(top: tuple[int, int, int], bot: tuple[int, int, int], w: int = 4) -> PILImage.Image:
    """2-row image: row 0 = top colour, row 1 = bot colour.

    Used with max_rows=1 so render_halfblock resizes to (w, 2) and each
    cell pair maps one-to-one to the two pixel rows.
    """
    img = PILImage.new("RGB", (w, 2))
    pixels = img.load()
    for x in range(w):
        pixels[x, 0] = top
        pixels[x, 1] = bot
    return img


def test_black_image_all_space():
    from hermes_cli.tui.kitty_graphics import render_halfblock, SPACE
    strips = render_halfblock(_solid((0, 0, 0)), max_cols=4, max_rows=2)
    for strip in strips:
        for seg in strip._segments:
            assert seg.text == SPACE


def test_white_image_all_block():
    from hermes_cli.tui.kitty_graphics import render_halfblock, BLOCK
    strips = render_halfblock(_solid((255, 255, 255)), max_cols=4, max_rows=2)
    for strip in strips:
        for seg in strip._segments:
            assert seg.text == BLOCK


def test_top_bright_bot_dark():
    from hermes_cli.tui.kitty_graphics import render_halfblock, HALF_UP, HALF_DOWN
    # max_rows=1 → resize to (4, 2): row0=white, row1=black
    img = _half(top=(255, 255, 255), bot=(0, 0, 0))
    strips = render_halfblock(img, max_cols=4, max_rows=1)
    chars = {seg.text for strip in strips for seg in strip._segments}
    # top bright + bot dark → HALF_UP (top half lit)
    assert HALF_UP in chars
    assert HALF_DOWN not in chars


def test_top_dark_bot_bright():
    from hermes_cli.tui.kitty_graphics import render_halfblock, HALF_UP, HALF_DOWN
    # max_rows=1 → resize to (4, 2): row0=black, row1=white
    img = _half(top=(0, 0, 0), bot=(255, 255, 255))
    strips = render_halfblock(img, max_cols=4, max_rows=1)
    chars = {seg.text for strip in strips for seg in strip._segments}
    # top dark + bot bright → HALF_DOWN (bottom half lit)
    assert HALF_DOWN in chars
    assert HALF_UP not in chars


def test_both_bright_uses_block():
    from hermes_cli.tui.kitty_graphics import render_halfblock, BLOCK
    img = _solid((200, 200, 200), w=4, h=4)
    strips = render_halfblock(img, max_cols=4, max_rows=2)
    chars = {seg.text for strip in strips for seg in strip._segments}
    assert BLOCK in chars


def test_output_row_count():
    from hermes_cli.tui.kitty_graphics import render_halfblock
    img = _solid((100, 100, 100), w=20, h=20)
    strips = render_halfblock(img, max_cols=20, max_rows=5)
    assert len(strips) <= 5


def test_output_col_count():
    from hermes_cli.tui.kitty_graphics import render_halfblock
    img = _solid((100, 100, 100), w=20, h=10)
    strips = render_halfblock(img, max_cols=20, max_rows=5)
    for strip in strips:
        assert len(strip._segments) <= 20


def test_rgba_input_no_crash():
    from hermes_cli.tui.kitty_graphics import render_halfblock
    img = PILImage.new("RGBA", (4, 4), (128, 64, 32, 200))
    strips = render_halfblock(img, max_cols=4, max_rows=2)
    assert isinstance(strips, list)


def test_palette_input_no_crash():
    from hermes_cli.tui.kitty_graphics import render_halfblock
    img = PILImage.new("P", (4, 4))
    strips = render_halfblock(img, max_cols=4, max_rows=2)
    assert isinstance(strips, list)


def test_returns_list_of_strips():
    from hermes_cli.tui.kitty_graphics import render_halfblock
    img = _solid((150, 100, 50))
    result = render_halfblock(img, max_cols=4, max_rows=2)
    assert isinstance(result, list)
    assert all(isinstance(s, Strip) for s in result)
