"""Tests for resize delta gates: RZ-MED-H5, RZ-MED-H6, RZ-MED-M3, RZ-MED-M6.

All tests use __new__ + manual attribute injection; no DOM mount required.
"""
from __future__ import annotations

import types
import unittest
import unittest.mock
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _size_ns(w: int, h: int) -> SimpleNamespace:
    """A SimpleNamespace mimicking textual.geometry.Size(w, h)."""
    return SimpleNamespace(width=w, height=h)


def _resize_event(w: int, h: int) -> SimpleNamespace:
    """Resize event with .size.width and .size.height."""
    return SimpleNamespace(size=_size_ns(w, h))


# ---------------------------------------------------------------------------
# RZ-MED-H5 — InlineImage: gate Kitty re-transmit on size change
# ---------------------------------------------------------------------------

class TestInlineImageTransmitGate(unittest.TestCase):
    """5 tests — H5"""

    def _make_widget(self) -> object:
        from hermes_cli.tui.widgets.inline_media import InlineImage
        obj = object.__new__(InlineImage)
        obj._last_resize_size = (-1, -1)
        return obj

    def test_first_resize_transmits(self) -> None:
        obj = self._make_widget()
        sentinel = object()
        obj._reactive_image = sentinel  # type: ignore[attr-defined]
        with unittest.mock.patch.object(obj, "watch_image") as mock_wi:
            obj.on_resize(_resize_event(40, 20))
        mock_wi.assert_called_once_with(sentinel)

    def test_identical_resize_skips_transmit(self) -> None:
        obj = self._make_widget()
        sentinel = object()
        obj._reactive_image = sentinel  # type: ignore[attr-defined]
        with unittest.mock.patch.object(obj, "watch_image") as mock_wi:
            obj.on_resize(_resize_event(40, 20))
            obj.on_resize(_resize_event(40, 20))
        self.assertEqual(mock_wi.call_count, 1)

    def test_width_change_transmits(self) -> None:
        obj = self._make_widget()
        sentinel = object()
        obj._reactive_image = sentinel  # type: ignore[attr-defined]
        with unittest.mock.patch.object(obj, "watch_image") as mock_wi:
            obj.on_resize(_resize_event(40, 20))
            obj.on_resize(_resize_event(50, 20))
        self.assertEqual(mock_wi.call_count, 2)

    def test_height_change_transmits(self) -> None:
        obj = self._make_widget()
        sentinel = object()
        obj._reactive_image = sentinel  # type: ignore[attr-defined]
        with unittest.mock.patch.object(obj, "watch_image") as mock_wi:
            obj.on_resize(_resize_event(40, 20))
            obj.on_resize(_resize_event(40, 25))
        self.assertEqual(mock_wi.call_count, 2)

    def test_resize_without_image_no_transmit(self) -> None:
        obj = self._make_widget()
        obj._reactive_image = None  # type: ignore[attr-defined]
        with unittest.mock.patch.object(obj, "watch_image") as mock_wi:
            obj.on_resize(_resize_event(40, 20))
        mock_wi.assert_not_called()


# ---------------------------------------------------------------------------
# RZ-MED-H6 — InlineProseLog: scope render-mode cache reset to cell-px change
# ---------------------------------------------------------------------------

class TestProseCellPxScope(unittest.TestCase):
    """4 tests — H6"""

    def _make_widget(self) -> object:
        from hermes_cli.tui.widgets.prose import InlineProseLog

        class _FakeCache:
            def invalidate_for_resize(self) -> None:
                pass

        obj = object.__new__(InlineProseLog)
        obj._last_cell_px = (0, 0)
        obj._render_mode_cache = "SENTINEL"  # non-None so we can detect clearing
        obj._image_cache = _FakeCache()
        obj._inline_lines = {}
        obj._inline_paint = {}
        obj._logical_visual_rows = {}
        return obj

    def test_first_resize_initializes_cell_px(self) -> None:
        obj = self._make_widget()
        with (
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._reset_cell_px_cache"
            ),
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)
            ),
            unittest.mock.patch.object(obj, "refresh") as mock_refresh,
        ):
            obj.on_resize(_resize_event(80, 24))
        self.assertIsNone(obj._render_mode_cache)
        self.assertEqual(obj._last_cell_px, (8, 16))
        mock_refresh.assert_called()

    def test_resize_with_unchanged_cell_px_skips_rebuild(self) -> None:
        obj = self._make_widget()
        obj._last_cell_px = (8, 16)
        obj._render_mode_cache = "SENTINEL"
        with (
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._reset_cell_px_cache"
            ),
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)
            ),
            unittest.mock.patch.object(obj, "refresh") as mock_refresh,
            unittest.mock.patch.object(
                obj, "_build_paint_plan"
            ) as mock_build,
        ):
            obj.on_resize(_resize_event(80, 24))
        # _render_mode_cache must NOT have been reset (still "SENTINEL")
        self.assertEqual(obj._render_mode_cache, "SENTINEL")
        mock_build.assert_not_called()
        mock_refresh.assert_called()

    def test_resize_with_changed_cell_px_rebuilds(self) -> None:
        obj = self._make_widget()
        obj._last_cell_px = (8, 16)
        obj._render_mode_cache = "SENTINEL"
        # Populate one inline line so _build_paint_plan is called
        fake_line = object()
        obj._inline_lines = {0: fake_line}
        with (
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._reset_cell_px_cache"
            ),
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._cell_px", return_value=(10, 20)
            ),
            unittest.mock.patch.object(
                obj, "_build_paint_plan", return_value=[]
            ) as mock_build,
            unittest.mock.patch.object(obj, "_line_to_text", return_value=""),
            unittest.mock.patch.object(obj, "_prerender_line_images"),
            unittest.mock.patch.object(obj, "refresh"),
        ):
            obj.on_resize(_resize_event(80, 24))
        self.assertIsNone(obj._render_mode_cache)
        mock_build.assert_called()

    def test_cell_px_cache_reset_every_resize(self) -> None:
        obj = self._make_widget()
        obj._last_cell_px = (8, 16)
        with (
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._reset_cell_px_cache"
            ) as mock_reset,
            unittest.mock.patch(
                "hermes_cli.tui.kitty_graphics._cell_px", return_value=(8, 16)
            ),
            unittest.mock.patch.object(obj, "refresh"),
        ):
            obj.on_resize(_resize_event(80, 24))
            obj.on_resize(_resize_event(80, 24))
        # Called once per on_resize invocation regardless of cell-px change
        self.assertEqual(mock_reset.call_count, 2)


# ---------------------------------------------------------------------------
# RZ-MED-M3 — InlineMediaWidget (spec: MediaPlayerWidget): gate seekbar refresh
# ---------------------------------------------------------------------------

class TestMediaSeekbarGate(unittest.TestCase):
    """3 tests — M3"""

    def _make_widget(self) -> object:
        from hermes_cli.tui.widgets.media import InlineMediaWidget
        obj = object.__new__(InlineMediaWidget)
        obj._last_seekbar_w = 0
        mock_seekbar = unittest.mock.MagicMock()
        obj._seekbar = mock_seekbar
        return obj

    def test_first_resize_refreshes_seekbar(self) -> None:
        obj = self._make_widget()
        obj.on_resize(_resize_event(60, 20))
        obj._seekbar.refresh.assert_called_once()  # type: ignore[attr-defined]

    def test_height_only_resize_skips_refresh(self) -> None:
        obj = self._make_widget()
        obj.on_resize(_resize_event(60, 20))
        obj.on_resize(_resize_event(60, 25))
        obj._seekbar.refresh.assert_called_once()  # type: ignore[attr-defined]

    def test_width_change_refreshes(self) -> None:
        obj = self._make_widget()
        obj.on_resize(_resize_event(60, 20))
        obj.on_resize(_resize_event(80, 20))
        self.assertEqual(obj._seekbar.refresh.call_count, 2)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# RZ-MED-M6 — DrawbrailleOverlay: gate anim params + refresh on dim change
# ---------------------------------------------------------------------------

class TestDrawbrailleResizeGate(unittest.TestCase):
    """5 tests — M6"""

    def _make_widget(self, w: int = 0, h: int = 0) -> object:
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
        obj = object.__new__(DrawbrailleOverlay)
        obj._anim_params = SimpleNamespace(width=w, height=h)
        obj.refresh = unittest.mock.MagicMock()
        return obj

    def _make_widget_no_params(self) -> object:
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
        obj = object.__new__(DrawbrailleOverlay)
        obj._anim_params = None
        obj.refresh = unittest.mock.MagicMock()
        return obj

    def test_first_resize_sets_dims_and_refreshes(self) -> None:
        obj = self._make_widget(w=0, h=0)
        obj.on_resize(_resize_event(40, 20))
        self.assertEqual(obj._anim_params.width, 80)   # type: ignore[attr-defined]
        self.assertEqual(obj._anim_params.height, 80)  # type: ignore[attr-defined]
        obj.refresh.assert_called_once()               # type: ignore[attr-defined]

    def test_identical_resize_skips_refresh(self) -> None:
        obj = self._make_widget(w=80, h=80)
        # Resize(40, 20) → width*2=80, height*4=80 — identical to current
        obj.on_resize(_resize_event(40, 20))
        obj.refresh.assert_not_called()  # type: ignore[attr-defined]

    def test_width_change_refreshes(self) -> None:
        obj = self._make_widget(w=80, h=80)
        # Resize(60, 20) → width*2=120, height*4=80
        obj.on_resize(_resize_event(60, 20))
        obj.refresh.assert_called_once()  # type: ignore[attr-defined]

    def test_height_change_refreshes(self) -> None:
        obj = self._make_widget(w=80, h=80)
        # Resize(40, 30) → width*2=80, height*4=120
        obj.on_resize(_resize_event(40, 30))
        obj.refresh.assert_called_once()  # type: ignore[attr-defined]

    def test_no_anim_params_no_op(self) -> None:
        obj = self._make_widget_no_params()
        # Must not raise and must not call refresh
        obj.on_resize(_resize_event(40, 20))
        obj.refresh.assert_not_called()  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
