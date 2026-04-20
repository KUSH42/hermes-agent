"""Tests for hermes_cli.tui.kitty_graphics — capability detection and wire format."""

from __future__ import annotations

import base64
import io
import re
import struct
import unittest.mock as mock

import pytest

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")


# ---------------------------------------------------------------------------
# Fixture: reset caps cache after every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_caps(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    yield
    from hermes_cli.tui.kitty_graphics import _reset_caps, _reset_cell_px_cache
    _reset_caps()
    _reset_cell_px_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_image(w: int = 4, h: int = 4, mode: str = "RGB") -> PILImage.Image:
    return PILImage.new(mode, (w, h), color=(128, 128, 128))


def _make_large_image(w: int = 500, h: int = 500) -> PILImage.Image:
    return PILImage.new("RGB", (w, h), color=(200, 100, 50))


# ---------------------------------------------------------------------------
# § Capability detection (7 tests)
# ---------------------------------------------------------------------------

def test_env_override_tgp(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "tgp")
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.TGP


def test_env_override_none(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.NONE


def test_env_override_halfblock(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "halfblock")
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.HALFBLOCK


def test_term_program_kitty(monkeypatch):
    monkeypatch.delenv("HERMES_GRAPHICS", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "kitty")
    monkeypatch.delenv("TMUX", raising=False)
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.TGP


def test_term_program_wezterm(monkeypatch):
    monkeypatch.delenv("HERMES_GRAPHICS", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "wezterm")
    monkeypatch.delenv("TMUX", raising=False)
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.TGP


def test_xterm_kitty_term(monkeypatch):
    monkeypatch.delenv("HERMES_GRAPHICS", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("TERM", "xterm-kitty")
    monkeypatch.delenv("TMUX", raising=False)
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.TGP


def test_tmux_forces_halfblock(monkeypatch):
    monkeypatch.delenv("HERMES_GRAPHICS", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "kitty")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1234/default,12345,0")
    from hermes_cli.tui.kitty_graphics import _reset_caps, get_caps, GraphicsCap
    _reset_caps()
    assert get_caps() == GraphicsCap.HALFBLOCK


# ---------------------------------------------------------------------------
# § Wire format (8 tests)
# ---------------------------------------------------------------------------

def test_single_chunk_sequence():
    from hermes_cli.tui.kitty_graphics import _build_tgp_sequence
    img = _make_image(1, 1)
    seq = _build_tgp_sequence(img, cols=1, rows=1, image_id=7)
    assert seq.startswith("\x1b_G")
    assert seq.endswith("\x1b\\")
    assert "m=0" in seq
    assert "m=1" not in seq


def test_multi_chunk_sequence():
    from hermes_cli.tui.kitty_graphics import _build_tgp_sequence
    img = _make_large_image(1000, 1000)
    seq = _build_tgp_sequence(img, cols=80, rows=24, image_id=42)
    # First chunk must have m=1
    first_chunk_end = seq.index("\x1b\\")
    first_chunk = seq[: first_chunk_end + 2]
    assert "m=1" in first_chunk
    # Last APC must have m=0
    last_apc_start = seq.rfind("\x1b_G")
    assert "m=0" in seq[last_apc_start:]


def test_chunk_boundary_4096():
    """Raw bytes that encode to exactly 4096 base64 chars → single chunk."""
    from hermes_cli.tui.kitty_graphics import _chunk_b64
    # 3072 raw bytes → 4096 base64 chars (3*n → 4*n)
    raw = bytes(range(256)) * 12  # 3072 bytes
    chunks = _chunk_b64(raw)
    assert len(chunks) == 1
    assert len(chunks[0]) == 4096


def test_chunk_boundary_4097():
    """Raw bytes that encode to 4097 base64 chars → 2 chunks."""
    from hermes_cli.tui.kitty_graphics import _chunk_b64
    # 3072 + 3 = 3075 bytes → 4100 base64 chars → 2 chunks
    raw = bytes(range(256)) * 12 + b"\x01\x02\x03"
    chunks = _chunk_b64(raw)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4096


def test_image_id_in_first_chunk_only():
    """i= appears in first chunk only; continuation chunks must not have i=."""
    from hermes_cli.tui.kitty_graphics import _build_tgp_sequence
    img = _make_large_image(1000, 1000)
    seq = _build_tgp_sequence(img, cols=80, rows=24, image_id=99)
    chunks = re.findall(r"\x1b_G(.*?)\x1b\\", seq)
    assert len(chunks) >= 2
    # First chunk has i=
    assert "i=99" in chunks[0]
    # No continuation chunk has i=
    for chunk in chunks[1:]:
        assert "i=" not in chunk


def test_delete_sequence_format():
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer()
    assert r.delete_sequence(42) == "\x1b_Ga=d,d=I,i=42;\x1b\\"


def test_delete_all_sequence_format():
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer()
    assert r.delete_all_sequence() == "\x1b_Ga=d,d=A;\x1b\\"


def test_q2_suppression_all_chunks():
    """Every APC chunk in a multi-chunk sequence must contain q=2."""
    from hermes_cli.tui.kitty_graphics import _build_tgp_sequence
    img = _make_large_image(1000, 1000)
    seq = _build_tgp_sequence(img, cols=80, rows=24, image_id=1)
    chunks = re.findall(r"\x1b_G(.*?)\x1b\\", seq)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert "q=2" in chunk, f"chunk missing q=2: {chunk[:60]!r}"


# ---------------------------------------------------------------------------
# § Sizing (4 tests)
# ---------------------------------------------------------------------------

def test_fit_image_shrinks_wide():
    from hermes_cli.tui.kitty_graphics import _fit_image
    img = _make_image(1600, 100)
    resized, cols, rows = _fit_image(img, max_cols=80, max_rows=24, cw=10, ch=20)
    assert cols <= 80


def test_fit_image_shrinks_tall():
    from hermes_cli.tui.kitty_graphics import _fit_image
    img = _make_image(100, 2400)
    resized, cols, rows = _fit_image(img, max_cols=80, max_rows=24, cw=10, ch=20)
    assert rows <= 24


def test_fit_image_preserves_aspect():
    from hermes_cli.tui.kitty_graphics import _fit_image
    img = _make_image(800, 400)  # 2:1 ratio
    resized, cols, rows = _fit_image(img, max_cols=80, max_rows=24, cw=10, ch=20)
    pw, ph = resized.size
    if ph > 0:
        ratio = pw / ph
        assert abs(ratio - 2.0) < 0.15, f"aspect ratio drifted: {ratio}"


def test_cell_px_fallback(monkeypatch):
    """When ioctl raises, _cell_px() returns (10, 20)."""
    import fcntl
    monkeypatch.setattr(fcntl, "ioctl", mock.Mock(side_effect=OSError("no tty")))
    monkeypatch.delenv("HERMES_CELL_PX", raising=False)
    from hermes_cli.tui.kitty_graphics import _cell_px, _reset_cell_px_cache
    _reset_cell_px_cache()
    assert _cell_px() == (10, 20)


# ---------------------------------------------------------------------------
# § ID management (1 test)
# ---------------------------------------------------------------------------

def test_alloc_id_wraps():
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer()
    r._next_id = 4_294_967_295
    first = r._alloc_id()
    assert first == 4_294_967_295
    second = r._alloc_id()
    assert second == 1


# ---------------------------------------------------------------------------
# § Unicode placeholder detection (3 tests)
# ---------------------------------------------------------------------------

def test_placeholder_xterm_kitty_term(monkeypatch):
    """TERM=xterm-kitty + KITTY_WINDOW_ID → placeholders supported."""
    from hermes_cli.tui.kitty_graphics import _reset_unicode_placeholders_cache, _supports_unicode_placeholders
    monkeypatch.setenv("TERM", "xterm-kitty")
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    _reset_unicode_placeholders_cache()
    assert _supports_unicode_placeholders() is True


def test_placeholder_term_program_kitty(monkeypatch):
    """TERM_PROGRAM=kitty + KITTY_WINDOW_ID → placeholders supported even if TERM != xterm-kitty."""
    from hermes_cli.tui.kitty_graphics import _reset_unicode_placeholders_cache, _supports_unicode_placeholders
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TERM_PROGRAM", "kitty")
    monkeypatch.setenv("KITTY_WINDOW_ID", "3")
    _reset_unicode_placeholders_cache()
    assert _supports_unicode_placeholders() is True


def test_placeholder_requires_window_id(monkeypatch):
    """TERM=xterm-kitty but no KITTY_WINDOW_ID → placeholders not supported."""
    from hermes_cli.tui.kitty_graphics import _reset_unicode_placeholders_cache, _supports_unicode_placeholders
    monkeypatch.setenv("TERM", "xterm-kitty")
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    _reset_unicode_placeholders_cache()
    assert _supports_unicode_placeholders() is False
