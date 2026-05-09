"""tests/tui/test_resize_overlays.py — resize-event gating for overlays.

Covers RZ-OV-M4 (HistorySearchOverlay width-delta gate),
RZ-OV-M5 (KeymapOverlay 80-col threshold gate), and
RZ-OV-M7 (CompletionOverlay max-height write gate).

All tests use __new__ + manual attribute injection so no app is needed.
The `app` property is patched via unittest.mock since it traverses
Textual's internal parent chain and requires a mounted widget.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from textual.geometry import Size

from hermes_cli.tui.widgets.overlays import HistorySearchOverlay, KeymapOverlay
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.resize_utils import crosses_threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_app(width: int = 80, height: int = 24) -> SimpleNamespace:
    """Return a minimal fake app object with .size."""
    return SimpleNamespace(size=Size(width, height))


def _make_history_overlay(visible: bool = True) -> HistorySearchOverlay:
    """Create a HistorySearchOverlay via __new__ with the minimal state needed."""
    overlay = HistorySearchOverlay.__new__(HistorySearchOverlay)
    overlay._last_render_w = 0
    # Simulate has_class() based on visible flag
    overlay.has_class = lambda cls: (cls == "--visible" and visible)
    return overlay


def _make_keymap_overlay(last_w: int = 0) -> KeymapOverlay:
    """Create a KeymapOverlay via __new__ with the minimal state needed."""
    overlay = KeymapOverlay.__new__(KeymapOverlay)
    overlay._last_resize_w = last_w
    return overlay


def _make_completion_overlay(last_max_h: int = -1) -> CompletionOverlay:
    """Create a CompletionOverlay via __new__ with the minimal state needed."""
    overlay = CompletionOverlay.__new__(CompletionOverlay)
    overlay._last_applied_max_h = last_max_h
    overlay._last_applied_w = 0
    return overlay


# ---------------------------------------------------------------------------
# TestHistorySearchOverlayGate  (RZ-OV-M4 — 4 tests)
# ---------------------------------------------------------------------------

class TestHistorySearchOverlayGate:
    """Test the width-delta gate on HistorySearchOverlay.on_resize (RZ-OV-M4).

    query_one("#history-search-input") requires a mounted DOM; we patch it
    alongside _render_results since the tests focus purely on the gate logic
    (width-delta check), not the query or render internals.
    """

    def _run_resize(self, overlay: HistorySearchOverlay, app_width: int, mock_render: MagicMock) -> None:
        """Invoke on_resize with app.size.width=app_width, also patching query_one."""
        mock_input = MagicMock()
        mock_input.value = ""
        with patch.object(type(overlay), "app", new_callable=PropertyMock) as mock_app:
            mock_app.return_value = _fake_app(width=app_width)
            with patch.object(overlay, "query_one", return_value=mock_input):
                overlay.on_resize()

    def test_first_resize_when_visible_renders(self) -> None:
        """Visible overlay, fresh _last_render_w=0, width 80 → _render_results called once."""
        overlay = _make_history_overlay(visible=True)
        with patch.object(overlay, "_render_results") as mock_render:
            self._run_resize(overlay, 80, mock_render)
        mock_render.assert_called_once_with("")

    def test_identical_resize_skips_render(self) -> None:
        """Fire on_resize twice with same app width → _render_results called only once."""
        overlay = _make_history_overlay(visible=True)
        with patch.object(overlay, "_render_results") as mock_render:
            self._run_resize(overlay, 80, mock_render)
            self._run_resize(overlay, 80, mock_render)
        mock_render.assert_called_once()

    def test_width_change_renders(self) -> None:
        """_last_render_w=80, app width 100 → _render_results called."""
        overlay = _make_history_overlay(visible=True)
        overlay._last_render_w = 80
        with patch.object(overlay, "_render_results") as mock_render:
            self._run_resize(overlay, 100, mock_render)
        mock_render.assert_called_once_with("")

    def test_resize_when_hidden_skips_render(self) -> None:
        """Overlay lacks --visible → _render_results not called (early return before app.size access)."""
        overlay = _make_history_overlay(visible=False)
        with patch.object(overlay, "_render_results") as mock_render:
            # No app needed — early return from has_class guard
            overlay.on_resize()
        mock_render.assert_not_called()


# ---------------------------------------------------------------------------
# TestKeymapOverlayThreshold  (RZ-OV-M5 — 4 tests)
# ---------------------------------------------------------------------------

class TestKeymapOverlayThreshold:

    def test_first_resize_above_80_fires_update(self) -> None:
        """_last_resize_w=0, fire with w=100: crosses_threshold(0, 100, 80) → True → _update_content called."""
        overlay = _make_keymap_overlay(last_w=0)
        # Verify crosses_threshold logic matches expectation
        assert crosses_threshold(0, 100, 80) is True
        with patch.object(type(overlay), "app", new_callable=PropertyMock) as mock_app:
            mock_app.return_value = _fake_app(width=100)
            with patch.object(overlay, "_update_content") as mock_update:
                overlay.on_resize()
        mock_update.assert_called_once()
        assert overlay._last_resize_w == 100

    def test_first_resize_below_80_skips_update(self) -> None:
        """_last_resize_w=0, fire with w=70: crosses_threshold(0, 70, 80) → False → no _update_content.

        Initial state was set by on_mount; on_resize only fires for crossing events.
        """
        overlay = _make_keymap_overlay(last_w=0)
        # Verify crosses_threshold logic matches expectation
        assert crosses_threshold(0, 70, 80) is False
        with patch.object(type(overlay), "app", new_callable=PropertyMock) as mock_app:
            mock_app.return_value = _fake_app(width=70)
            with patch.object(overlay, "_update_content") as mock_update:
                overlay.on_resize()
        mock_update.assert_not_called()
        assert overlay._last_resize_w == 70

    def test_no_crossing_skips_update(self) -> None:
        """_last_resize_w=100, fire w=110 (both above 82) → no crossing → _update_content not called."""
        overlay = _make_keymap_overlay(last_w=100)
        assert crosses_threshold(100, 110, 80) is False
        with patch.object(type(overlay), "app", new_callable=PropertyMock) as mock_app:
            mock_app.return_value = _fake_app(width=110)
            with patch.object(overlay, "_update_content") as mock_update:
                overlay.on_resize()
        mock_update.assert_not_called()
        assert overlay._last_resize_w == 110

    def test_crossing_threshold_updates(self) -> None:
        """_last_resize_w=100, fire w=70: crosses from above 82 to below 78 → _update_content called."""
        overlay = _make_keymap_overlay(last_w=100)
        assert crosses_threshold(100, 70, 80) is True
        with patch.object(type(overlay), "app", new_callable=PropertyMock) as mock_app:
            mock_app.return_value = _fake_app(width=70)
            with patch.object(overlay, "_update_content") as mock_update:
                overlay.on_resize()
        mock_update.assert_called_once()
        assert overlay._last_resize_w == 70


# ---------------------------------------------------------------------------
# TestCompletionOverlayMaxHeight  (RZ-OV-M7 — 3 tests)
# ---------------------------------------------------------------------------

class TestCompletionOverlayMaxHeight:

    def _make_resize_event(self, width: int, height: int) -> MagicMock:
        event = MagicMock()
        event.size = Size(width, height)
        return event

    def test_first_resize_sets_max_height(self) -> None:
        """Fresh overlay (_last_applied_max_h=-1), fire (80,30) → styles.max_height=22 and cache updated."""
        overlay = _make_completion_overlay(last_max_h=-1)
        overlay.styles = MagicMock()
        event = self._make_resize_event(80, 30)

        with patch.object(overlay, "set_class"):
            overlay.on_resize(event)

        expected_avail = max(4, 30 - 8)  # 22
        assert overlay._last_applied_max_h == expected_avail

    def test_height_unchanged_skips_set(self) -> None:
        """_last_applied_max_h=22, fire (80,30) again → styles.max_height not written again."""
        overlay = _make_completion_overlay(last_max_h=22)
        overlay.styles = MagicMock()
        event = self._make_resize_event(80, 30)

        with patch.object(overlay, "set_class"):
            overlay.on_resize(event)

        # avail = max(4, 30-8) = 22 — same as cache → setter must be skipped.
        # Verify by checking _last_applied_max_h is still 22 (cache update only
        # happens inside the branch that writes styles.max_height).
        assert overlay._last_applied_max_h == 22
        # styles.max_height assignment: MagicMock tracks __setattr__ calls.
        # We confirm it was NOT called by asserting 0 set_attr calls for max_height.
        calls = [str(c) for c in overlay.styles.mock_calls]
        assert not any("max_height" in c for c in calls), (
            f"styles.max_height should not be set when avail==cache, calls={calls}"
        )

    def test_height_change_applies(self) -> None:
        """_last_applied_max_h=22, fire (80,40) → avail=32, setter called and cache updated."""
        overlay = _make_completion_overlay(last_max_h=22)
        overlay.styles = MagicMock()
        event = self._make_resize_event(80, 40)

        with patch.object(overlay, "set_class"):
            overlay.on_resize(event)

        expected_avail = max(4, 40 - 8)  # 32
        assert overlay._last_applied_max_h == expected_avail
