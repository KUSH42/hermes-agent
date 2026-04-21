"""Phase D tests: inline_images config, luminance threshold config, threading."""

from __future__ import annotations

import threading

import pytest

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _PIL_AVAILABLE, reason="PIL not installed")

from textual.strip import Strip


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_kitty_state(monkeypatch):
    monkeypatch.setenv("HERMES_GRAPHICS", "none")
    yield
    from hermes_cli.tui.kitty_graphics import _reset_caps, _reset_renderer, _reset_phase_d
    _reset_caps()
    _reset_renderer()
    _reset_phase_d()


def _solid(color: tuple[int, int, int], w: int = 4, h: int = 4) -> PILImage.Image:
    return PILImage.new("RGB", (w, h), color=color)


def _make_inline_image(max_rows: int = 24):
    from hermes_cli.tui.widgets import InlineImage
    return InlineImage(max_rows=max_rows)


# ---------------------------------------------------------------------------
# inline_images mode
# ---------------------------------------------------------------------------

def test_default_inline_images_mode_is_auto():
    from hermes_cli.tui.kitty_graphics import get_inline_images_mode, _reset_phase_d
    _reset_phase_d()
    assert get_inline_images_mode() == "auto"


def test_set_inline_images_mode_off():
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode, get_inline_images_mode
    set_inline_images_mode("off")
    assert get_inline_images_mode() == "off"


def test_set_inline_images_mode_on():
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode, get_inline_images_mode
    set_inline_images_mode("on")
    assert get_inline_images_mode() == "on"


def test_set_inline_images_mode_invalid_falls_back_to_auto():
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode, get_inline_images_mode
    set_inline_images_mode("garbage")
    assert get_inline_images_mode() == "auto"


def test_watch_image_off_mode_clears_seq(tmp_path):
    """With inline_images=off, watch_image sets _tgp_seq to ''."""
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode
    set_inline_images_mode("off")
    path = tmp_path / "img.png"
    PILImage.new("RGB", (10, 10), color=(200, 100, 50)).save(str(path))
    w = _make_inline_image()
    w._tgp_seq = "something"
    w.watch_image(str(path))
    assert w._tgp_seq == ""


def test_watch_image_off_renders_placeholder(tmp_path):
    """With inline_images=off, render_line returns placeholder."""
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode
    set_inline_images_mode("off")
    w = _make_inline_image()
    w._src_path = "/tmp/fake.png"
    strip = w._render_placeholder_line(0)
    text = "".join(seg.text for seg in strip._segments)
    assert "[image:" in text


def test_watch_image_off_resets_rendered_rows(tmp_path):
    """inline_images=off forces _rendered_rows=1."""
    from hermes_cli.tui.kitty_graphics import set_inline_images_mode
    set_inline_images_mode("off")
    path = tmp_path / "img.png"
    PILImage.new("RGB", (10, 10)).save(str(path))
    w = _make_inline_image()
    w._rendered_rows = 5
    w.watch_image(str(path))
    assert w._rendered_rows == 1


# ---------------------------------------------------------------------------
# Luminance / dark threshold
# ---------------------------------------------------------------------------

def test_default_dark_threshold():
    from hermes_cli.tui.kitty_graphics import get_dark_threshold, _reset_phase_d
    _reset_phase_d()
    assert get_dark_threshold() == pytest.approx(0.1)


def test_set_dark_threshold():
    from hermes_cli.tui.kitty_graphics import set_dark_threshold, get_dark_threshold
    set_dark_threshold(0.25)
    assert get_dark_threshold() == pytest.approx(0.25)


def test_render_halfblock_uses_dark_threshold_low():
    """Low dark_threshold=0.0: even black pixels are not 'dark' → colored chars."""
    from hermes_cli.tui.kitty_graphics import render_halfblock, SPACE
    img = _solid((0, 0, 0))  # luminance = 0.0
    strips = render_halfblock(img, max_cols=4, max_rows=2, dark_threshold=0.0)
    chars = {seg.text for strip in strips for seg in strip._segments}
    # With threshold=0.0, luminance(0,0,0)=0.0 is NOT < 0.0 → not dark → colored block
    assert SPACE not in chars


def test_render_halfblock_uses_dark_threshold_high():
    """High dark_threshold=1.0: all pixels are dark → all SPACE."""
    from hermes_cli.tui.kitty_graphics import render_halfblock, SPACE
    img = _solid((200, 200, 200))  # luminance ~0.58, < 1.0 → dark
    strips = render_halfblock(img, max_cols=4, max_rows=2, dark_threshold=1.0)
    chars = {seg.text for strip in strips for seg in strip._segments}
    assert SPACE in chars


def test_module_dark_threshold_affects_render():
    """set_dark_threshold propagates to render_halfblock default."""
    from hermes_cli.tui.kitty_graphics import render_halfblock, set_dark_threshold, SPACE
    # threshold=1.0: everything dark → all SPACE
    set_dark_threshold(1.0)
    img = _solid((200, 200, 200))
    strips = render_halfblock(img, max_cols=4, max_rows=2)  # uses module default
    chars = {seg.text for strip in strips for seg in strip._segments}
    assert SPACE in chars


# ---------------------------------------------------------------------------
# Threading — KittyRenderer lock
# ---------------------------------------------------------------------------

def test_renderer_has_id_lock():
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer(cw=10, ch=20)
    assert isinstance(r._id_lock, type(threading.Lock()))


def test_alloc_id_thread_safe():
    """Concurrent _alloc_id calls from multiple threads yield unique IDs."""
    from hermes_cli.tui.kitty_graphics import KittyRenderer
    r = KittyRenderer(cw=10, ch=20)
    results = []
    lock = threading.Lock()

    def alloc():
        for _ in range(50):
            iid = r._alloc_id()
            with lock:
                results.append(iid)

    threads = [threading.Thread(target=alloc) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == len(set(results)), "duplicate IDs detected under concurrent access"


# ---------------------------------------------------------------------------
# Threading — LARGE_IMAGE_BYTES threshold constant
# ---------------------------------------------------------------------------

def test_large_image_bytes_constant():
    from hermes_cli.tui.kitty_graphics import LARGE_IMAGE_BYTES
    assert LARGE_IMAGE_BYTES == 2_000_000


def test_large_image_threshold_calculation():
    """Verify threshold logic: width * height * 4 > LARGE_IMAGE_BYTES."""
    from hermes_cli.tui.kitty_graphics import LARGE_IMAGE_BYTES
    # ~707x707 = ~2M pixels → 4 channels → threshold
    small_w, small_h = 100, 100  # 100*100*4 = 40_000 → small
    large_w, large_h = 1000, 600  # 1000*600*4 = 2_400_000 → large
    assert small_w * small_h * 4 <= LARGE_IMAGE_BYTES
    assert large_w * large_h * 4 > LARGE_IMAGE_BYTES


# ---------------------------------------------------------------------------
# _apply_tgp_result
# ---------------------------------------------------------------------------

def test_apply_tgp_result_sets_widget_state():
    """_apply_tgp_result updates all image fields."""
    w = _make_inline_image()
    # Simulate is_mounted=True by patching
    w._is_mounted = True
    import unittest.mock as mock
    with mock.patch.object(type(w), "is_mounted", new_callable=lambda: property(lambda self: True)):
        w.refresh = mock.MagicMock()
        w._apply_tgp_result("SEQ", 42, 10, 8)
    assert w._image_id == 42
    assert w._tgp_seq == "SEQ"
    assert w._rendered_rows == 8


def test_apply_tgp_result_skips_when_unmounted():
    """_apply_tgp_result is a no-op when widget is not mounted."""
    w = _make_inline_image()
    import unittest.mock as mock
    w.refresh = mock.MagicMock()
    with mock.patch.object(type(w), "is_mounted", new_callable=lambda: property(lambda self: False)):
        w._apply_tgp_result("SEQ", 99, 5, 4)
    # State should NOT be updated
    assert w._image_id is None
    assert w._tgp_seq == ""
    assert w._rendered_rows == 1
    w.refresh.assert_not_called()
