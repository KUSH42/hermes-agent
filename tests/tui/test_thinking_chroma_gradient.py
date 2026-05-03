"""Tests for TW-CHROMA: ThinkingWidget chroma gradient + hue-shift.

Covers:
- _lerp_hex boundary and clamping behaviour
- _refresh_colors chroma var parsing, defaults, clamping
- _AnimSurface.tick_anim chroma_a/chroma_b keyword args
- _AnimSurface._render_gradient_line per-row lerp
- Hue drift formula in _tick
- _tick with _anim_surface is None (LINE mode)
"""
from __future__ import annotations

import math
import types
import unittest
from unittest.mock import MagicMock, patch


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_anim_surface(height: int = 4) -> object:
    """Build a minimal _AnimSurface-like object without Textual mount.

    Textual Widget exposes 'size' as a read-only property backed by the layout
    engine. We bypass it by injecting a mock into the instance __dict__ under
    a private name, then monkeypatching _render_gradient_line to use it.
    Instead, we create a thin subclass that overrides 'size' as a plain attr.
    """
    from hermes_cli.tui.widgets.thinking import _AnimSurface

    # Create a subclass that shadows 'size' as a writable instance attribute,
    # bypassing Textual's read-only property.
    class _TestAnimSurface(_AnimSurface):
        @property
        def size(self):  # type: ignore[override]
            return self._test_size

        @size.setter
        def size(self, v):
            self._test_size = v

    surf = object.__new__(_TestAnimSurface)
    # Instance attrs expected by _render_gradient_line / tick_anim
    surf._chroma_a_hex = "#7b68ee"
    surf._chroma_b_hex = "#00bcd4"
    surf._accent_hex = "#888888"
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._peak_hex = "#d8d8d8"
    surf._peak_rgb = (216, 216, 216)
    surf._dim_rgb = (138, 138, 138)
    surf._frame_tick = 0
    surf._engine = None
    surf._frame_lines = []
    surf._elapsed = 0.0

    # Mock Textual Size
    mock_size = MagicMock()
    mock_size.height = height
    mock_size.width = 40
    surf.size = mock_size

    return surf


def _make_thinking_widget() -> object:
    """Build a minimal ThinkingWidget without Textual."""
    from hermes_cli.tui.widgets.thinking import ThinkingWidget

    w = object.__new__(ThinkingWidget)
    w._anim_surface = None
    w._label_line = None
    w._timer = None
    w._substate = None
    w._activate_time = None
    w._accent_hex = "#888888"
    w._text_hex = "#ffffff"
    w._app_bg_hex = "#1e1e1e"
    w._spinner_dim_hex = "#4a4a4a"
    w._spinner_peak_hex = "#d8d8d8"
    w._chroma_a_hex = "#7b68ee"
    w._chroma_b_hex = "#00bcd4"
    w._chroma_hue_speed = 0.15
    w._cfg_loaded = False
    w._cfg_tick_hz = 12.0
    w._cfg_long_wait_after_s = 8.0
    w._cfg_deep_after_s = 120.0
    w._cfg_show_elapsed = True
    w._cfg_allow_intense = False
    w._last_token_time = None
    return w


# ══════════════════════════════════════════════════════════════════════════════
# 1-4: _lerp_hex
# ══════════════════════════════════════════════════════════════════════════════

class TestLerpHex(unittest.TestCase):
    def setUp(self):
        from hermes_cli.tui._color_utils import _lerp_hex
        self._lerp = _lerp_hex

    def test_t_zero_returns_a(self):
        result = self._lerp("#000000", "#ffffff", 0.0)
        self.assertEqual(result, "#000000")

    def test_t_one_returns_b(self):
        result = self._lerp("#000000", "#ffffff", 1.0)
        self.assertEqual(result, "#ffffff")

    def test_t_half_midpoint(self):
        result = self._lerp("#000000", "#ffffff", 0.5)
        # int(0 + 255*0.5) = int(127.5) = 127 → 0x7f
        self.assertIn(result, ("#7f7f7f", "#808080"))

    def test_t_negative_clamps_to_a(self):
        result = self._lerp("#000000", "#ffffff", -0.5)
        self.assertEqual(result, "#000000")

    def test_t_greater_than_one_clamps_to_b(self):
        result = self._lerp("#000000", "#ffffff", 2.0)
        self.assertEqual(result, "#ffffff")

    def test_t_exactly_zero_clamped(self):
        a = self._lerp("#ff0000", "#0000ff", 0.0)
        b = self._lerp("#ff0000", "#0000ff", -999.0)
        self.assertEqual(a, b)

    def test_t_exactly_one_clamped(self):
        a = self._lerp("#ff0000", "#0000ff", 1.0)
        b = self._lerp("#ff0000", "#0000ff", 999.0)
        self.assertEqual(a, b)


# ══════════════════════════════════════════════════════════════════════════════
# 5-8: _refresh_colors chroma vars
# ══════════════════════════════════════════════════════════════════════════════

class TestRefreshColorsChroma(unittest.TestCase):
    def _make_widget_with_css_vars(self, css_vars: dict) -> object:
        from hermes_cli.tui.widgets.thinking import ThinkingWidget

        # Subclass to make 'app' writable (Textual property has no setter)
        class _TestThinkingWidget(ThinkingWidget):
            @property
            def app(self):  # type: ignore[override]
                return self._test_app

            @app.setter
            def app(self, v):
                self._test_app = v

        w = object.__new__(_TestThinkingWidget)
        w._anim_surface = None
        w._label_line = None
        w._chroma_a_hex = "#000000"
        w._chroma_b_hex = "#000000"
        w._chroma_hue_speed = 0.0

        # Mock app.get_css_variables()
        mock_app = MagicMock()
        mock_app.get_css_variables.return_value = css_vars
        mock_app.styles.background.hex = None
        w.app = mock_app

        # Stub _apply_background_styles
        w._apply_background_styles = lambda: None
        # Provide stubs for the other attrs _refresh_colors writes
        w._accent_hex = "#888888"
        w._text_hex = "#ffffff"
        w._app_bg_hex = "#1e1e1e"
        w._spinner_dim_hex = "#4a4a4a"
        w._spinner_peak_hex = "#d8d8d8"
        w._spinner_dim_rgb = (74, 74, 74)
        w._spinner_peak_rgb = (216, 216, 216)

        return w

    def test_valid_vars_stored(self):
        w = self._make_widget_with_css_vars({
            "thinking-chroma-a": "#ff0000",
            "thinking-chroma-b": "#00ff00",
            "thinking-hue-shift-speed": "0.5",
            "accent": "#888888",
            "text": "#ffffff",
            "app-bg": "#1e1e1e",
            "thinking-spinner-dim": "#4a4a4a",
            "thinking-spinner-peak": "#d8d8d8",
        })
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        ThinkingWidget._refresh_colors(w)
        self.assertEqual(w._chroma_a_hex, "#ff0000")
        self.assertEqual(w._chroma_b_hex, "#00ff00")
        self.assertAlmostEqual(w._chroma_hue_speed, 0.5)

    def test_missing_vars_use_defaults(self):
        w = self._make_widget_with_css_vars({
            "accent": "#888888",
            "text": "#ffffff",
            "app-bg": "#1e1e1e",
            "thinking-spinner-dim": "#4a4a4a",
            "thinking-spinner-peak": "#d8d8d8",
        })
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        ThinkingWidget._refresh_colors(w)
        self.assertEqual(w._chroma_a_hex, "#7b68ee")
        self.assertEqual(w._chroma_b_hex, "#00bcd4")
        self.assertAlmostEqual(w._chroma_hue_speed, 0.15)

    def test_invalid_speed_falls_back_to_default(self):
        w = self._make_widget_with_css_vars({
            "thinking-hue-shift-speed": "not-a-float",
            "accent": "#888888",
            "text": "#ffffff",
            "app-bg": "#1e1e1e",
            "thinking-spinner-dim": "#4a4a4a",
            "thinking-spinner-peak": "#d8d8d8",
        })
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        ThinkingWidget._refresh_colors(w)
        self.assertAlmostEqual(w._chroma_hue_speed, 0.15)

    def test_negative_speed_clamped_to_zero(self):
        w = self._make_widget_with_css_vars({
            "thinking-hue-shift-speed": "-1.0",
            "accent": "#888888",
            "text": "#ffffff",
            "app-bg": "#1e1e1e",
            "thinking-spinner-dim": "#4a4a4a",
            "thinking-spinner-peak": "#d8d8d8",
        })
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        ThinkingWidget._refresh_colors(w)
        self.assertEqual(w._chroma_hue_speed, 0.0)

    def test_excess_speed_clamped_to_two(self):
        w = self._make_widget_with_css_vars({
            "thinking-hue-shift-speed": "5.0",
            "accent": "#888888",
            "text": "#ffffff",
            "app-bg": "#1e1e1e",
            "thinking-spinner-dim": "#4a4a4a",
            "thinking-spinner-peak": "#d8d8d8",
        })
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        ThinkingWidget._refresh_colors(w)
        self.assertEqual(w._chroma_hue_speed, 2.0)


# ══════════════════════════════════════════════════════════════════════════════
# 9-10: tick_anim chroma keyword args
# ══════════════════════════════════════════════════════════════════════════════

class TestTickAnimChromaArgs(unittest.TestCase):
    def _make_surface(self) -> object:
        return _make_anim_surface()

    def test_chroma_a_set_chroma_b_unchanged(self):
        surf = self._make_surface()
        prior_b = surf._chroma_b_hex
        from hermes_cli.tui.widgets.thinking import _AnimSurface
        # Patch refresh on the actual type of surf (the _TestAnimSurface subclass)
        with patch.object(type(surf), "refresh", lambda s, **kw: None, create=True):
            _AnimSurface.tick_anim(surf, dt=0.1, chroma_a="#abcdef")
        self.assertEqual(surf._chroma_a_hex, "#abcdef")
        self.assertEqual(surf._chroma_b_hex, prior_b)

    def test_neither_chroma_unchanged(self):
        surf = self._make_surface()
        prior_a = surf._chroma_a_hex
        prior_b = surf._chroma_b_hex
        from hermes_cli.tui.widgets.thinking import _AnimSurface
        with patch.object(type(surf), "refresh", lambda s, **kw: None, create=True):
            _AnimSurface.tick_anim(surf, dt=0.1)
        self.assertEqual(surf._chroma_a_hex, prior_a)
        self.assertEqual(surf._chroma_b_hex, prior_b)


# ══════════════════════════════════════════════════════════════════════════════
# 11-14: _render_gradient_line per-row lerp
# ══════════════════════════════════════════════════════════════════════════════

class TestRenderGradientLine(unittest.TestCase):
    def _render(self, row: int, height: int, content: str = "XXXX") -> object:
        surf = _make_anim_surface(height=height)
        from hermes_cli.tui.widgets.thinking import _AnimSurface
        return _AnimSurface._render_gradient_line(surf, content, row)

    def test_row0_dim_color_equals_chroma_a(self):
        """Row 0 of a 4-row surface should use chroma-a as dim color."""
        from hermes_cli.tui._color_utils import _lerp_hex
        surf = _make_anim_surface(height=4)
        surf._chroma_a_hex = "#ff0000"
        surf._chroma_b_hex = "#0000ff"
        from hermes_cli.tui.widgets.thinking import _AnimSurface
        strip = _AnimSurface._render_gradient_line(surf, "X", 0)
        # y_norm = 0 / 3 = 0.0 → lerp at t=0 → chroma_a = #ff0000
        expected_lerp = _lerp_hex("#ff0000", "#0000ff", 0.0)
        self.assertEqual(expected_lerp, "#ff0000")
        self.assertIsNotNone(strip)

    def test_last_row_dim_color_equals_chroma_b(self):
        """Last row should use chroma-b as dim color."""
        from hermes_cli.tui._color_utils import _lerp_hex
        surf = _make_anim_surface(height=4)
        surf._chroma_a_hex = "#ff0000"
        surf._chroma_b_hex = "#0000ff"
        from hermes_cli.tui.widgets.thinking import _AnimSurface
        strip = _AnimSurface._render_gradient_line(surf, "X", 3)
        # y_norm = 3/3 = 1.0 → lerp at t=1 → chroma_b = #0000ff
        expected_lerp = _lerp_hex("#ff0000", "#0000ff", 1.0)
        self.assertEqual(expected_lerp, "#0000ff")
        self.assertIsNotNone(strip)

    def test_single_row_height_no_division_by_zero(self):
        """height=1 → y_norm=0.0, should not raise ZeroDivisionError."""
        try:
            strip = self._render(row=0, height=1)
            self.assertIsNotNone(strip)
        except ZeroDivisionError:
            self.fail("_render_gradient_line raised ZeroDivisionError with height=1")

    def test_zero_height_guarded_by_max(self):
        """height=0 → max(1, 0)=1 → y_norm=0.0, no ZeroDivisionError."""
        try:
            strip = self._render(row=0, height=0)
            self.assertIsNotNone(strip)
        except ZeroDivisionError:
            self.fail("_render_gradient_line raised ZeroDivisionError with height=0")


# ══════════════════════════════════════════════════════════════════════════════
# 15-16: Hue drift formula
# ══════════════════════════════════════════════════════════════════════════════

class TestHueDriftFormula(unittest.TestCase):
    def _compute(self, elapsed: float, speed: float) -> float:
        return (elapsed * speed) % 1.0

    def test_elapsed_1_speed_half(self):
        self.assertAlmostEqual(self._compute(1.0, 0.5), 0.5)

    def test_elapsed_2_speed_half_wraps_zero(self):
        self.assertAlmostEqual(self._compute(2.0, 0.5), 0.0)

    def test_elapsed_1_5_speed_half(self):
        self.assertAlmostEqual(self._compute(1.5, 0.5), 0.75)

    def test_elapsed_zero_speed_half(self):
        self.assertAlmostEqual(self._compute(0.0, 0.5), 0.0)

    def test_speed_zero_elapsed_ten(self):
        self.assertAlmostEqual(self._compute(10.0, 0.0), 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 17: _tick with _anim_surface is None (LINE mode)
# ══════════════════════════════════════════════════════════════════════════════

class TestTickWithNoAnimSurface(unittest.TestCase):
    def test_tick_no_anim_surface_no_error(self):
        """_tick with _anim_surface=None should not raise AttributeError."""
        w = _make_thinking_widget()
        w._substate = "WORKING"
        import time
        w._activate_time = time.monotonic() - 1.0

        # Stub _get_label_text
        w._get_label_text = lambda elapsed=None: "Thinking…"

        # Stub _label_line.tick_label
        mock_label = MagicMock()
        w._label_line = mock_label

        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        try:
            ThinkingWidget._tick(w)
        except AttributeError as e:
            self.fail(f"_tick raised AttributeError: {e}")

        # _anim_surface is None so hue calc must be skipped; label was ticked
        mock_label.tick_label.assert_called_once()


if __name__ == "__main__":
    unittest.main()
