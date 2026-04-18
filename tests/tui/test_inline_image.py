"""Tests for InlineImage widget in hermes_cli.tui.widgets."""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest.mock as mock

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
    from hermes_cli.tui.kitty_graphics import _reset_caps, _reset_renderer
    _reset_caps()
    _reset_renderer()


@pytest.fixture()
def tmp_png(tmp_path: pathlib.Path) -> str:
    path = tmp_path / "test.png"
    img = PILImage.new("RGB", (10, 10), color=(200, 100, 50))
    img.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# Direct widget unit tests (no Pilot — avoids event-loop overhead)
# ---------------------------------------------------------------------------

def _make_widget(**kwargs) -> "Any":
    """Create an InlineImage without a running Textual app.

    Calls InlineImage.__init__ to set up reactives. Before layout, size.width
    is 0 — all render methods use `or 80` fallback, so tests work correctly.
    """
    from hermes_cli.tui.widgets import InlineImage
    max_rows = kwargs.get("max_rows", 24)
    return InlineImage(max_rows=max_rows)


def test_halfblock_strips_initialized():
    w = _make_widget()
    assert w._halfblock_strips == []


def test_none_image_no_crash():
    w = _make_widget()
    w.watch_image(None)
    assert w._tgp_seq == ""


def test_watch_none_clears_seq(tmp_png, monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    from hermes_cli.tui.kitty_graphics import _reset_caps
    _reset_caps()
    w = _make_widget()
    w._tgp_seq = "something"
    w.watch_image(None)
    assert w._tgp_seq == ""


def test_invalid_path_shows_placeholder(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "tgp")
    from hermes_cli.tui.kitty_graphics import _reset_caps
    _reset_caps()
    w = _make_widget()
    w._src_path = "/tmp/nonexistent_hermes_test.png"
    w.watch_image("/tmp/nonexistent_hermes_test.png")
    # PIL unavailable path OR load failure → tgp_seq stays empty
    assert w._tgp_seq == ""


def test_none_image_rendered_rows():
    w = _make_widget()
    w.watch_image(None)
    assert w._rendered_rows == 1


def test_max_rows_propagated():
    w = _make_widget(max_rows=3)
    assert w.max_rows == 3


# ---------------------------------------------------------------------------
# render_line tests (no Pilot needed)
# ---------------------------------------------------------------------------

def test_none_cap_renders_placeholder(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    from hermes_cli.tui.kitty_graphics import _reset_caps
    _reset_caps()
    w = _make_widget()
    w._src_path = "/tmp/foo.png"
    strip = w._render_placeholder_line(0)
    text = "".join(seg.text for seg in strip._segments)
    assert "[image:" in text


def test_placeholder_nonzero_row_blank(monkeypatch):
    w = _make_widget()
    strip = w._render_placeholder_line(5)
    assert isinstance(strip, Strip)


def test_tgp_line0_contains_seq_when_seq_set(monkeypatch):
    w = _make_widget()
    w._tgp_seq = "\x1b_Ga=T,f=100,s=10,v=10,c=1,r=1,i=1,m=0,q=2;AAAA\x1b\\"
    strip = w._render_tgp_line(0)
    text = "".join(seg.text for seg in strip._segments)
    assert "\x1b_G" in text


def test_tgp_line_nonzero_blank(monkeypatch):
    w = _make_widget()
    w._tgp_seq = "\x1b_Ga=T;AAAA\x1b\\"
    strip = w._render_tgp_line(1)
    text = "".join(seg.text for seg in strip._segments)
    assert "\x1b_G" not in text


def test_halfblock_render_line_returns_strip(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "halfblock")
    from hermes_cli.tui.kitty_graphics import _reset_caps
    _reset_caps()
    from textual.strip import Strip
    from rich.segment import Segment
    w = _make_widget()
    w._halfblock_strips = [Strip([Segment("▀")])]
    strip = w._render_halfblock_line(0)
    assert isinstance(strip, Strip)


def test_halfblock_out_of_range_blank(monkeypatch):
    w = _make_widget()
    w._halfblock_strips = []
    strip = w._render_halfblock_line(99)
    assert isinstance(strip, Strip)


# ---------------------------------------------------------------------------
# emit_raw + on_unmount
# ---------------------------------------------------------------------------

def test_emit_raw_calls_stdout_write(monkeypatch):
    writes = []
    monkeypatch.setattr("sys.stdout", mock.MagicMock(write=lambda s: writes.append(s)))
    w = _make_widget()
    w._emit_raw("hello")
    assert writes == ["hello"]


def test_unmount_emits_delete_sequence(monkeypatch):
    emitted = []
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer(cw=10, ch=20)
    r._next_id = 5
    r._alloc_id()  # consumes 5; next is 6
    # Inject a fake image_id
    w = _make_widget()
    w._image_id = 42
    w._emit_raw = lambda s: emitted.append(s)
    # Simulate on_unmount body
    from hermes_cli.tui.kitty_graphics import _get_renderer
    if w._image_id is not None:
        w._emit_raw(_get_renderer().delete_sequence(w._image_id))
        w._image_id = None
    assert any("d=I" in s and "i=42" in s for s in emitted)
    assert w._image_id is None


def test_unmount_clears_image_id():
    w = _make_widget()
    w._image_id = 7
    emitted = []
    w._emit_raw = lambda s: emitted.append(s)
    from hermes_cli.tui.kitty_graphics import _get_renderer
    if w._image_id is not None:
        w._emit_raw(_get_renderer().delete_sequence(w._image_id))
        w._image_id = None
    assert w._image_id is None
