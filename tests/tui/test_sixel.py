"""Tests for Sixel renderer — probe detection, encoding, RLE, and InlineImage integration."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hermes_cli.tui.kitty_graphics import (
    GraphicsCap,
    _reset_caps,
    _sixel_rle,
    _to_sixel,
    get_caps,
)

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


pytestmark = pytest.mark.usefixtures("_reset_caps_fixture")


@pytest.fixture(autouse=True)
def _reset_caps_fixture():
    _reset_caps()
    yield
    _reset_caps()


# ---------------------------------------------------------------------------
# Detection via env override
# ---------------------------------------------------------------------------

def test_sixel_probe_detected_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_GRAPHICS", "sixel")
    _reset_caps()
    assert get_caps() == GraphicsCap.SIXEL


# ---------------------------------------------------------------------------
# _sixel_rle
# ---------------------------------------------------------------------------

def test_sixel_rle_no_run() -> None:
    assert _sixel_rle("ABC") == "ABC"


def test_sixel_rle_short_run() -> None:
    assert _sixel_rle("AAB") == "AAB"


def test_sixel_rle_long_run() -> None:
    assert _sixel_rle("AAAA") == "!4A"


def test_sixel_rle_mixed() -> None:
    assert _sixel_rle("AAAABBC") == "!4ABBC"


def test_sixel_rle_single_char() -> None:
    assert _sixel_rle("X") == "X"


def test_sixel_rle_all_same() -> None:
    assert _sixel_rle("ZZZZZZ") == "!6Z"


# ---------------------------------------------------------------------------
# _to_sixel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_to_sixel_returns_string() -> None:
    img = PILImage.new("RGB", (4, 4), color=(128, 64, 32))
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)):
        result = _to_sixel(img, max_cols=10, max_rows=6)
    assert isinstance(result, str)
    assert result.startswith("\x1bP")


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_to_sixel_ends_with_st() -> None:
    img = PILImage.new("RGB", (4, 4), color=(200, 100, 50))
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)):
        result = _to_sixel(img, max_cols=10, max_rows=6)
    assert result.endswith("\x1b\\")


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_to_sixel_contains_colour_register() -> None:
    img = PILImage.new("RGB", (4, 4), color=(255, 0, 0))
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)):
        result = _to_sixel(img, max_cols=10, max_rows=6)
    assert "#0;2;" in result


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_pil_unavailable_returns_empty() -> None:
    img = PILImage.new("RGB", (4, 4))
    with patch("hermes_cli.tui.kitty_graphics._PIL_AVAILABLE", False):
        result = _to_sixel(img)
    assert result == ""


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_small_image_produces_output() -> None:
    img = PILImage.new("RGB", (4, 4), color=(10, 20, 30))
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)):
        result = _to_sixel(img, max_cols=10, max_rows=6)
    assert len(result) > 0


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_rgba_image_no_crash() -> None:
    img = PILImage.new("RGBA", (4, 4), color=(10, 20, 30, 200))
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)):
        result = _to_sixel(img, max_cols=10, max_rows=6)
    assert isinstance(result, str)


def test_cell_px_zero_returns_empty() -> None:
    from hermes_cli.tui.kitty_graphics import _to_sixel
    with patch("hermes_cli.tui.kitty_graphics._cell_px", return_value=(0, 0)):
        if _PIL_AVAILABLE:
            img = PILImage.new("RGB", (4, 4))
        else:
            img = MagicMock()
        # Should return "" without crashing
        result = _to_sixel(img)
    assert result == ""


# ---------------------------------------------------------------------------
# InlineImage — Sixel integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_inline_image_has_sixel_seq_attr() -> None:
    from hermes_cli.tui.widgets import InlineImage
    img_widget = InlineImage()
    assert hasattr(img_widget, "_sixel_seq")
    assert img_widget._sixel_seq == ""


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_render_sixel_line_y0_returns_sequence() -> None:
    from hermes_cli.tui.widgets import InlineImage
    from textual.strip import Strip
    widget = InlineImage()
    widget._sixel_seq = "\x1bPq#0;2;50;0;0$-\x1b\\"
    result = widget._render_sixel_line(0)
    assert isinstance(result, Strip)


@pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")
def test_render_sixel_line_y1_returns_blank() -> None:
    from hermes_cli.tui.widgets import InlineImage
    from textual.strip import Strip
    widget = InlineImage()
    widget._sixel_seq = "\x1bPq#0;2;50;0;0$-\x1b\\"
    result = widget._render_sixel_line(1)
    assert isinstance(result, Strip)
    # Blank strip — no Sixel escape sequence content on subsequent rows
    plain = "".join(s.text for s in result)
    assert "\x1bP" not in plain


def test_sixel_no_cleanup_on_unmount() -> None:
    from hermes_cli.tui.widgets import InlineImage
    widget = InlineImage()
    widget._image_id = None
    widget._sixel_seq = "\x1bPq\x1b\\"
    # on_unmount only emits delete if _image_id is set (TGP-only cleanup)
    mock_emit = []
    widget._emit_raw = lambda s: mock_emit.append(s)
    widget.on_unmount()
    # No Sixel cleanup sequence expected
    assert all("\x1bPq" not in s for s in mock_emit)
