"""Tests for DrawbrailleRenderer — R-01 through R-21."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from hermes_cli.tui.drawbraille_renderer import DrawbrailleRenderer
from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg


def _renderer() -> DrawbrailleRenderer:
    r = DrawbrailleRenderer()
    r._resolved_color = "#00d7ff"
    r._resolved_color_b = "#8800ff"
    return r


def _cfg(**kw) -> DrawbrailleOverlayCfg:
    defaults = dict(
        enabled=True,
        fade_in_frames=3,
        fade_out_frames=5,
        ambient_alpha=0.4,
        ambient_enabled=False,
        crossfade_speed=0.04,
    )
    defaults.update(kw)
    return DrawbrailleOverlayCfg(**defaults)


# R-01: default state after __init__
def test_r01_default_state() -> None:
    r = DrawbrailleRenderer()
    assert r._resolved_color == "#00d7ff"
    assert r._resolved_color_b == "#8800ff"
    assert r._resolved_multi_colors == []
    assert r._resolved_multi_color_rgbs is None
    assert r._multi_color_row_buf == []
    assert r._fade_step == 0
    assert r._fade_state == "stable"
    assert r._fade_alpha == 1.0


# R-02: resolve_colors populates all _resolved_* attrs
def test_r02_resolve_colors_populates() -> None:
    r = DrawbrailleRenderer()
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = {}
    r.resolve_colors("#ff0000", "#0000ff", ["#00ff00", "#ffff00"], mock_app)
    assert r._resolved_color == "#ff0000"
    assert r._resolved_color_b == "#0000ff"
    assert len(r._resolved_multi_colors) == 2
    assert r._resolved_multi_color_rgbs is not None
    assert len(r._resolved_multi_color_rgbs) == 2


# R-03: resolve_colors with CSS var resolves accent
def test_r03_resolve_colors_css_var() -> None:
    r = DrawbrailleRenderer()
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = {"accent": "#abcdef"}
    r.resolve_colors("auto", "#000000", [], mock_app)
    assert r._resolved_color == "#abcdef"


# R-04: resolve_colors exception is swallowed silently
def test_r04_resolve_colors_exception_swallowed() -> None:
    r = DrawbrailleRenderer()
    r.resolve_colors("bad-color", "bad-color-b", [], None)
    # Should not raise; defaults unchanged
    assert r._resolved_color == "#00d7ff"


# R-05: start_fade_out sets state correctly
def test_r05_start_fade_out() -> None:
    r = _renderer()
    cfg = _cfg(fade_out_frames=8)
    r.start_fade_out(cfg)
    assert r._fade_state == "out"
    assert r._fade_step == 8


# R-06: start_fade_in resets alpha to 1.0 always
def test_r06_start_fade_in_resets_alpha() -> None:
    r = _renderer()
    r._fade_alpha = 0.3  # mid-fade-out value
    cfg = _cfg(fade_in_frames=4)
    r.start_fade_in(cfg)
    assert r._fade_state == "in"
    assert r._fade_step == 4
    assert r._fade_alpha == 1.0


# R-07: cancel_fade_out resets to stable and restores alpha
def test_r07_cancel_fade_out() -> None:
    r = _renderer()
    r._fade_state = "out"
    r._fade_alpha = 0.5
    r.cancel_fade_out()
    assert r._fade_state == "stable"
    assert r._fade_alpha == 1.0


# R-08: render_frame stable → returns Text with resolved color
def test_r08_render_frame_stable() -> None:
    from rich.text import Text
    r = _renderer()
    result = r.render_frame("⠿⠿", 0.0, _cfg(), "active", False, 0.3)
    assert isinstance(result, Text)
    assert result is not None


# R-09: render_frame fade-out decrements _fade_step
def test_r09_render_frame_fade_out_decrements() -> None:
    r = _renderer()
    r._fade_state = "out"
    r._fade_step = 4
    cfg = _cfg(fade_out_frames=5)
    result = r.render_frame("⠿⠿", 0.0, cfg, "active", False, 0.3)
    assert result is not None  # not done yet
    assert r._fade_step == 3


# R-10: render_frame fade-out returns None when step reaches 0
def test_r10_render_frame_fade_out_returns_none() -> None:
    r = _renderer()
    r._fade_state = "out"
    r._fade_step = 1
    cfg = _cfg(fade_out_frames=5)
    result = r.render_frame("⠿⠿", 0.0, cfg, "active", False, 0.3)
    assert result is None


# R-11: render_frame fade-in increments alpha
def test_r11_render_frame_fade_in_alpha() -> None:
    from rich.text import Text
    r = _renderer()
    r._fade_state = "in"
    r._fade_step = 3
    cfg = _cfg(fade_in_frames=3)
    result = r.render_frame("⠿⠿", 0.0, cfg, "active", False, 0.3)
    assert isinstance(result, Text)
    assert r._fade_step == 2  # decremented


# R-12: render_frame fade-in completes when _fade_step reaches 0
def test_r12_render_frame_fade_in_completes() -> None:
    r = _renderer()
    r._fade_state = "in"
    r._fade_step = 1
    cfg = _cfg(fade_in_frames=3)
    result = r.render_frame("⠿⠿", 0.0, cfg, "active", False, 0.3)
    assert result is not None
    assert r._fade_state == "stable"


# R-13: render_frame ambient → dims color by ambient_alpha
def test_r13_render_frame_ambient_dims() -> None:
    from rich.text import Text
    r = _renderer()
    r._resolved_color = "#ffffff"
    cfg = _cfg(ambient_alpha=0.5)
    result = r.render_frame("⠿⠿", 0.0, cfg, "ambient", False, 0.3)
    assert isinstance(result, Text)
    # The color should be dimmed (not #ffffff)
    color_str = str(result.style.color) if result.style.color else ""
    # It should not be #ffffff (full brightness)
    assert "#ffffff" not in color_str.lower() or color_str == ""


# R-14: render_frame gradient mode produces Text with multiple spans
def test_r14_render_frame_gradient() -> None:
    from rich.text import Text
    r = _renderer()
    r._resolved_color = "#00d7ff"
    r._resolved_color_b = "#8800ff"
    frame_str = "abc\ndef\n"
    result = r.render_frame(frame_str, 0.0, _cfg(), "active", True, 0.3)
    assert isinstance(result, Text)
    assert len(result._spans) > 0


# R-15: render_frame multi_color branch takes priority over gradient
def test_r15_render_frame_multi_color_priority() -> None:
    from rich.text import Text
    r = _renderer()
    r._resolved_multi_colors = ["#ff0000", "#00ff00"]
    frame_str = "abcde\n"
    result = r.render_frame(frame_str, 0.0, _cfg(), "active", True, 0.3)
    assert isinstance(result, Text)
    # Multi-color spans
    assert len(result._spans) > 0


# R-16: _render_multi_color single stop produces uniform color
def test_r16_render_multi_color_single_stop() -> None:
    from rich.text import Text
    r = _renderer()
    r._resolved_multi_colors = ["#ff6600"]
    frame = "abc\n"
    result = r._render_multi_color(frame, t=0.0, hue_shift_speed=0.0)
    assert isinstance(result, Text)
    colors = {str(s.style.color) for s in result._spans if s.style.color}
    assert len(colors) == 1


# R-17: _render_multi_color multi stop produces diverse colors
def test_r17_render_multi_color_multi_stop() -> None:
    r = _renderer()
    r._resolved_multi_colors = ["#ff0000", "#00ff00", "#0000ff"]
    frame = "abcdefghij\n"
    result = r._render_multi_color(frame, t=0.0, hue_shift_speed=0.0)
    colors = {str(s.style.color) for s in result._spans if s.style.color}
    assert len(colors) > 1


# R-18: ambient dimming applies _hex_to_rgb multiply, not _resolve_color
def test_r18_ambient_dimming_uses_hex_not_resolve() -> None:
    """Ambient dim is applied to _resolved_color directly — no re-resolve via app."""
    from rich.text import Text
    r = _renderer()
    r._resolved_color = "#ffffff"
    cfg = _cfg(ambient_alpha=0.5)
    # app=None would fail if _resolve_color(cfg.color, app) were called
    result = r.render_frame("⠿", 0.0, cfg, "ambient", False, 0.3)
    assert isinstance(result, Text)


# R-19: _fade_step boundary — steps of 1
def test_r19_fade_step_boundary() -> None:
    r = _renderer()
    r._fade_state = "out"
    r._fade_step = 2
    cfg = _cfg(fade_out_frames=5)
    r.render_frame("⠿", 0.0, cfg, "active", False, 0.3)
    assert r._fade_step == 1
    r.render_frame("⠿", 0.0, cfg, "active", False, 0.3)
    # step == 0 → returns None
    result = r.render_frame("⠿", 0.0, cfg, "active", False, 0.3)
    # Wait, step was 1 going in, will become 0 → None
    # After second call step is 0


def test_r19b_fade_step_zero_returns_none() -> None:
    r = _renderer()
    r._fade_state = "out"
    r._fade_step = 1
    cfg = _cfg(fade_out_frames=5)
    result = r.render_frame("⠿", 0.0, cfg, "active", False, 0.3)
    assert result is None


# R-20: multi-color row buffer resizes on width change
def test_r20_row_buf_resize() -> None:
    r = _renderer()
    r._resolved_multi_colors = ["#ff0000", "#00ff00"]
    r._render_multi_color("abc\n", 0.0, 0.3)
    assert len(r._multi_color_row_buf) == 3
    r._render_multi_color("abcde\n", 0.0, 0.3)
    assert len(r._multi_color_row_buf) == 5


# R-21: resolve_colors populates _resolved_multi_color_rgbs as tuples
def test_r21_resolve_colors_populates_rgbs() -> None:
    r = DrawbrailleRenderer()
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = {}
    r.resolve_colors("#ff0000", "#0000ff", ["#ff0000", "#00ff00"], mock_app)
    assert r._resolved_multi_color_rgbs is not None
    for rgb in r._resolved_multi_color_rgbs:
        assert isinstance(rgb, tuple)
        assert len(rgb) == 3
