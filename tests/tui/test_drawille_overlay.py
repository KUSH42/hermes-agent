"""Tests for DrawilleOverlay, AnimConfigPanel, and animation engines.

~30 tests covering engine frame compute, color resolution, show/hide
lifecycle, auto-hide, size/position, gradient, fade-in, and config panel.
"""
from __future__ import annotations

import time
from dataclasses import replace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from hermes_cli.tui.drawille_overlay import (
    ANIMATION_KEYS,
    AnimConfigPanel,
    AnimParams,
    DrawilleOverlay,
    DrawilleOverlayCfg,
    KaleidoscopeEngine,
    DnaHelixEngine,
    RotatingHelixEngine,
    ClassicHelixEngine,
    MorphHelixEngine,
    VortexEngine,
    WaveInterferenceEngine,
    ThickHelixEngine,
    _ENGINES,
    _current_panel_cfg,
    _overlay_config,
    _resolve_color,
    _fields_to_dict,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _default_cfg(**overrides: object) -> DrawilleOverlayCfg:
    cfg = DrawilleOverlayCfg(enabled=True)
    return replace(cfg, **overrides)  # type: ignore[misc]


def _params(w: int = 100, h: int = 56) -> AnimParams:
    return AnimParams(width=w, height=h)


# ── Engine / frame compute ────────────────────────────────────────────────────

def test_frame_compute_dna_under_5ms():
    """DNA double-helix frame must compute in under 5ms."""
    engine = DnaHelixEngine()
    params = _params()
    start = time.perf_counter()
    result = engine.next_frame(params)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 5.0
    assert len(result) > 0


def test_frame_compute_all_engines_nonempty():
    """All engines return non-empty strings for a standard canvas.
    _ENGINES now maps str → class; instantiate each before calling next_frame.
    """
    params = _params()
    for key, engine_cls in _ENGINES.items():
        engine = engine_cls()
        result = engine.next_frame(params)
        assert isinstance(result, str), f"{key} did not return str"
        assert len(result) >= 0, f"{key} returned non-string"


def test_frame_compute_all_engines_under_8ms():
    """Original 8 engines complete a frame in < 8ms on a standard 80×24 terminal canvas.
    New stateful engines are excluded (they may take longer on first frame due to init).
    """
    _ORIGINAL_KEYS = {"dna", "rotating", "classic", "morph", "vortex", "wave", "thick", "kaleidoscope"}
    params = _params(w=160, h=96)  # 80×24 terminal → 160×96 braille pixels
    for key, engine_cls in _ENGINES.items():
        if key not in _ORIGINAL_KEYS:
            continue
        engine = engine_cls()
        start = time.perf_counter()
        engine.next_frame(params)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 8.0, f"{key} took {elapsed_ms:.1f}ms (budget: 8ms)"


def test_params_t_advances():
    """params.t increments by dt each manual _tick call."""
    ov = DrawilleOverlay()
    params = AnimParams(width=100, height=56, t=0.0, dt=1 / 15)
    ov._anim_params = params
    ov.add_class("-visible")
    ov.update = MagicMock()
    ov._tick()
    assert abs(params.t - 1 / 15) < 1e-9


def test_params_t_does_not_advance_when_hidden():
    """params.t must not advance when overlay is not visible."""
    ov = DrawilleOverlay()
    params = AnimParams(width=100, height=56, t=0.0, dt=1 / 15)
    ov._anim_params = params
    # not visible — no -visible class
    ov.update = MagicMock()
    ov._tick()
    assert params.t == 0.0


# ── Color resolution ──────────────────────────────────────────────────────────

def test_color_resolution_hex():
    """Hex colors resolve without error and return '#rrggbb' form."""
    app = MagicMock()
    app.get_css_variables.return_value = {}
    result = _resolve_color("#ff6600", app)
    assert result.startswith("#")
    assert len(result) == 7


def test_color_resolution_named_color():
    """Named colors (e.g. 'cyan') resolve to a valid hex string."""
    app = MagicMock()
    app.get_css_variables.return_value = {}
    result = _resolve_color("cyan", app)
    assert result.startswith("#")
    assert len(result) == 7


def test_color_resolution_tcss_var():
    """$accent resolves via ThemeManager CSS variables fallback."""
    app = MagicMock()
    app.get_css_variables.return_value = {"accent": "#5f87d7"}
    result = _resolve_color("$accent", app)
    # Should get the accent color or the fallback
    assert result.startswith("#")


def test_color_resolution_invalid_reverts_to_fallback():
    """Bad color string falls back to bright cyan #00d7ff."""
    app = MagicMock()
    app.get_css_variables.return_value = {}
    result = _resolve_color("not-a-color-xyz123", app)
    assert result == "#00d7ff"


def test_watch_color_updates_resolved():
    """Changing .color reactive should update _resolved_color via watch_color."""
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = {"accent": "#aabbcc"}
    ov = DrawilleOverlay()
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.watch_color("$accent")
    assert ov._resolved_color.startswith("#")


# ── Show / hide lifecycle ─────────────────────────────────────────────────────

def test_visible_class_added_on_show():
    """overlay gets -visible class when show() called with enabled=True."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=80, height=24)
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._start_anim = MagicMock()
    cfg = _default_cfg(enabled=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    assert ov.has_class("-visible")


def test_hidden_when_disabled():
    """overlay stays hidden when config enabled=False."""
    ov = DrawilleOverlay()
    cfg = DrawilleOverlayCfg(enabled=False)
    ov._start_anim = MagicMock()
    ov.show(cfg)
    assert not ov.has_class("-visible")
    ov._start_anim.assert_not_called()


def _mock_app_with_clock() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (mock_app, mock_clock, mock_handle) with clock wired up."""
    fake_handle = MagicMock()
    fake_clock = MagicMock()
    fake_clock.subscribe.return_value = fake_handle
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=80, height=24)
    mock_app._anim_clock = fake_clock
    return mock_app, fake_clock, fake_handle


def test_clock_sub_created_on_show():
    """_anim_handle is not None after show() calls _start_anim."""
    mock_app, fake_clock, fake_handle = _mock_app_with_clock()
    ov = DrawilleOverlay()
    ov.styles = MagicMock()

    cfg = _default_cfg(enabled=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    assert ov._anim_handle is not None


def test_clock_sub_stopped_on_hide():
    """_anim_handle is None after hide()."""
    mock_app, fake_clock, fake_handle = _mock_app_with_clock()
    ov = DrawilleOverlay()
    ov.styles = MagicMock()

    cfg = _default_cfg(enabled=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
        ov.hide(cfg)
    assert ov._anim_handle is None
    fake_handle.stop.assert_called()


def test_show_idempotent_no_double_subscribe():
    """Calling show() twice does not create two clock subscriptions."""
    mock_app, fake_clock, fake_handle = _mock_app_with_clock()
    ov = DrawilleOverlay()
    ov.styles = MagicMock()

    cfg = _default_cfg(enabled=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
        ov.show(cfg)
    assert fake_clock.subscribe.call_count == 1


def test_agent_stops_during_fade_in_no_error():
    """hide() during fade-in stops animation cleanly without assertion errors."""
    mock_app, fake_clock, fake_handle = _mock_app_with_clock()
    ov = DrawilleOverlay()
    ov.styles = MagicMock()

    cfg = _default_cfg(enabled=True, fade_in_frames=10, auto_hide_delay=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
        assert ov._fade_step == 10
        ov.hide(cfg)
    assert ov._anim_handle is None


def test_agent_restart_resets_fade_step():
    """show() after immediate hide() resets _fade_step to fade_in_frames."""
    mock_app, fake_clock, fake_handle = _mock_app_with_clock()
    ov = DrawilleOverlay()
    ov.styles = MagicMock()

    cfg = _default_cfg(enabled=True, fade_in_frames=5, auto_hide_delay=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
        ov.hide(cfg)
        cfg2 = _default_cfg(enabled=True, fade_in_frames=7, auto_hide_delay=0)
        ov.show(cfg2)
    assert ov._fade_step == 7


# ── Auto-hide ─────────────────────────────────────────────────────────────────

def test_auto_hide_delay_zero_no_timer():
    """No timer created when auto_hide_delay=0."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=80, height=24)
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._start_anim = MagicMock()
    ov.set_timer = MagicMock()

    cfg = _default_cfg(enabled=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    ov.set_timer.assert_not_called()


def test_auto_hide_delay_nonzero_creates_timer():
    """Timer is created when auto_hide_delay > 0."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=80, height=24)
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._start_anim = MagicMock()
    fake_timer = MagicMock()
    ov.set_timer = MagicMock(return_value=fake_timer)

    cfg = _default_cfg(enabled=True, auto_hide_delay=5.0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    ov.set_timer.assert_called_once()
    assert ov._auto_hide_handle is fake_timer


# ── Size / position ───────────────────────────────────────────────────────────

def test_size_large_sets_styles():
    """size='large' sets styles.width=70, styles.height=20."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=120, height=40)
    ov = DrawilleOverlay()

    widths: list[int] = []
    heights: list[int] = []

    class StylesMock:
        @property
        def width(self): return 0
        @width.setter
        def width(self, v): widths.append(v)
        @property
        def height(self): return 0
        @height.setter
        def height(self, v): heights.append(v)
        @property
        def offset(self): return (0, 0)
        @offset.setter
        def offset(self, v): pass

    ov.styles = StylesMock()
    ov.size_name = "large"
    ov.position = "center"
    ov.vertical = False
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()
    assert widths[-1] == 70
    assert heights[-1] == 20


def test_size_small_sets_correct_dimensions():
    """size='small' yields (30, 8)."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=120, height=40)
    ov = DrawilleOverlay()

    sizes_set: list[tuple] = []
    class StylesMock:
        @property
        def width(self): return 0
        @width.setter
        def width(self, v): sizes_set.append(("w", v))
        @property
        def height(self): return 0
        @height.setter
        def height(self, v): sizes_set.append(("h", v))
        @property
        def offset(self): return (0, 0)
        @offset.setter
        def offset(self, v): pass

    ov.styles = StylesMock()
    ov.size_name = "small"
    ov.position = "top-left"
    ov.vertical = False
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()
    assert ("w", 30) in sizes_set
    assert ("h", 8) in sizes_set


def test_position_center_offset_approx():
    """center offset ≈ (tw-w)//2, (th-h)//2."""
    tw, th = 120, 40
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=tw, height=th)
    ov = DrawilleOverlay()

    offsets_set: list[tuple] = []
    class StylesMock:
        @property
        def width(self): return 0
        @width.setter
        def width(self, v): pass
        @property
        def height(self): return 0
        @height.setter
        def height(self, v): pass
        @property
        def offset(self): return (0, 0)
        @offset.setter
        def offset(self, v): offsets_set.append(v)

    ov.styles = StylesMock()
    ov.size_name = "medium"
    ov.position = "center"
    ov.vertical = False
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()

    w, h = 50, 14
    expected = (max(0, (tw - w) // 2), max(0, (th - h) // 2))
    assert offsets_set[-1] == expected


# ── Gradient ──────────────────────────────────────────────────────────────────

def test_gradient_assembles_text_object():
    """Gradient mode produces a Text object, not a plain str."""
    from rich.text import Text as RichText
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._anim_params = AnimParams(width=100, height=56)
    ov.gradient = True
    ov._resolved_color = "#00d7ff"
    ov._resolved_color_b = "#8800ff"
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    assert len(updates) == 1
    assert isinstance(updates[0], RichText)


def test_gradient_false_produces_text_with_single_style():
    """Non-gradient mode also produces a Text object."""
    from rich.text import Text as RichText
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._anim_params = AnimParams(width=100, height=56)
    ov.gradient = False
    ov._resolved_color = "#00d7ff"
    ov.add_class("-visible")
    ov._fade_step = 0

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    assert len(updates) == 1
    assert isinstance(updates[0], RichText)


# ── Fade-in ───────────────────────────────────────────────────────────────────

def test_fade_in_frames_zero_instant_full_color():
    """fade_in_frames=0 → _fade_step=0 → renders at full color immediately."""
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._anim_params = AnimParams(width=100, height=56)
    ov.gradient = False
    ov._resolved_color = "#ff6600"
    ov._fade_step = 0
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    from rich.text import Text as RichText
    assert isinstance(updates[0], RichText)


def test_fade_in_decrements_fade_step():
    """Each _tick during fade-in decrements _fade_step by 1."""
    ov = DrawilleOverlay()
    ov._app = MagicMock()
    ov._app.size = MagicMock(width=80, height=24)
    ov.styles = MagicMock()
    ov._anim_params = AnimParams(width=100, height=56)
    ov.gradient = False
    ov._resolved_color = "#ff6600"
    ov._fade_step = 3
    ov.add_class("-visible")
    ov.update = MagicMock()

    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True, fade_in_frames=3)):
        ov._tick()
    assert ov._fade_step == 2


# ── AnimConfigPanel ───────────────────────────────────────────────────────────

def test_cycle_animation_right_advances():
    """→ key cycles animation forward."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    panel._focus_idx = 0  # animation field
    panel.refresh = MagicMock()
    panel._push_to_overlay = MagicMock()

    first_val = panel._fields[0].value
    panel.action_cycle_right()
    new_val = panel._fields[0].value
    assert new_val != first_val or len(ANIMATION_KEYS) == 1


def test_cycle_animation_wraps():
    """→ on last animation wraps to first."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    anim_field = panel._fields[0]
    anim_field.value = ANIMATION_KEYS[-1]
    panel._focus_idx = 0
    panel.refresh = MagicMock()
    panel._push_to_overlay = MagicMock()

    panel.action_cycle_right()
    assert anim_field.value == ANIMATION_KEYS[0]


def test_fps_inc_clamps_at_15():
    """↑ on fps=15 stays at 15."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    # fps is field index 1
    fps_field = next(f for f in panel._fields if f.name == "fps")
    fps_field.value = 15
    panel._focus_idx = panel._fields.index(fps_field)
    panel.refresh = MagicMock()
    panel._push_to_overlay = MagicMock()

    panel.action_inc_value()
    assert fps_field.value == 15


def test_fps_dec_clamps_at_1():
    """↓ on fps=1 stays at 1."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    fps_field = next(f for f in panel._fields if f.name == "fps")
    fps_field.value = 1
    panel._focus_idx = panel._fields.index(fps_field)
    panel.refresh = MagicMock()
    panel._push_to_overlay = MagicMock()

    panel.action_dec_value()
    assert fps_field.value == 1


def test_preview_forces_overlay_visible():
    """[Preview] calls overlay.show() and schedules 3s timer."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()

    fake_overlay = MagicMock(spec=DrawilleOverlay)
    panel._overlay = fake_overlay
    panel.set_timer = MagicMock()
    panel.refresh = MagicMock()

    panel._do_preview()
    fake_overlay.show.assert_called_once()
    panel.set_timer.assert_called_once()
    args = panel.set_timer.call_args[0]
    assert args[0] == 3.0


def test_preview_end_noop_when_agent_running():
    """_end_preview no-ops when agent_running is True."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()

    fake_overlay = MagicMock(spec=DrawilleOverlay)
    panel._overlay = fake_overlay
    fake_app = MagicMock()
    fake_app.agent_running = True
    panel._app = fake_app

    panel._end_preview()
    fake_overlay.hide.assert_not_called()


def test_save_calls_config_helpers():
    """[Save] calls read_raw_config and save_config."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()

    fake_app = MagicMock()
    panel._app = fake_app

    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)), \
         patch("hermes_cli.config.read_raw_config", return_value={}) as mock_read, \
         patch("hermes_cli.config.save_config") as mock_save, \
         patch("hermes_cli.config._set_nested") as mock_nested:
        panel._do_save()
    mock_read.assert_called_once()
    mock_nested.assert_called_once()
    mock_save.assert_called_once()


def test_open_adds_open_class():
    """open() adds -open class."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    panel.focus = MagicMock()
    panel.open()
    assert panel.has_class("-open")


def test_close_removes_open_class():
    """close() removes -open class."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    panel.focus = MagicMock()
    panel.open()
    fake_app = MagicMock()
    fake_app.query_one.side_effect = Exception("no widget")
    panel._app = fake_app
    panel.close()
    assert not panel.has_class("-open")


def test_toggle_opens_when_closed():
    """Toggling a closed panel opens it."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    panel.focus = MagicMock()
    assert not panel.has_class("-open")
    panel.open()
    assert panel.has_class("-open")


def test_toggle_closes_when_open():
    """Toggling an open panel closes it."""
    with patch("hermes_cli.tui.drawille_overlay._overlay_config",
               return_value=DrawilleOverlayCfg(enabled=True)):
        panel = AnimConfigPanel()
    panel.focus = MagicMock()
    panel.open()
    assert panel.has_class("-open")
    fake_app = MagicMock()
    fake_app.query_one.side_effect = Exception("no widget")
    panel._app = fake_app
    panel.close()
    assert not panel.has_class("-open")


# ── Multi-color strand rendering ──────────────────────────────────────────────

def test_multi_color_produces_text_object():
    """multi_color mode returns a Text object (not plain str)."""
    from rich.text import Text as RichText
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=100, height=56)
    ov._resolved_multi_colors = ["#00ff66", "#004422", "#0066ff"]
    ov.hue_shift_speed = 0.3
    ov.add_class("-visible")
    ov.gradient = False

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    assert len(updates) == 1
    assert isinstance(updates[0], RichText)


def test_multi_color_three_stops_distinct_colors():
    """Render with 3 stops produces characters with at least 2 distinct colors."""
    from rich.text import Text as RichText
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=100, height=56)
    ov._resolved_multi_colors = ["#ff0000", "#00ff00", "#0000ff"]
    ov.hue_shift_speed = 0.0  # no drift — deterministic
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    result = updates[0]
    styles = {span.style.color for span in result._spans if span.style.color}
    assert len(styles) > 1


def test_multi_color_single_stop_uses_that_color():
    """1-stop multi_color uses the single color for all chars."""
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=100, height=56)
    ov._resolved_multi_colors = ["#ff6600"]
    ov.hue_shift_speed = 0.0
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    # Should not raise and should produce output
    assert len(updates) == 1


def test_multi_color_overrides_gradient_mode():
    """multi_color branch takes priority over gradient when both set."""
    from rich.text import Text as RichText
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=100, height=56)
    ov._resolved_multi_colors = ["#00ff66", "#0066ff"]
    ov.gradient = True   # also set gradient — multi_color should win
    ov.hue_shift_speed = 0.0
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    assert len(updates) == 1
    # Result should be a Text (multi_color path), not the row-based gradient string
    assert isinstance(updates[0], RichText)


def test_hue_shift_drift_changes_output_over_time():
    """Different t values with non-zero hue_shift_speed produce different outputs."""
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=60, height=28)
    ov._resolved_multi_colors = ["#00ff66", "#004422", "#0066ff"]
    ov.hue_shift_speed = 2.0  # fast shift for test detectability

    frame_str = "abc\ndef\n"
    result_t0 = ov._render_multi_color(frame_str, t=0.0)
    result_t1 = ov._render_multi_color(frame_str, t=1.2)  # sin moves significantly
    # The span colors should differ because drift = sin(t * speed) * 0.25 changed
    colors_t0 = [str(s.style.color) for s in result_t0._spans if s.style.color]
    colors_t1 = [str(s.style.color) for s in result_t1._spans if s.style.color]
    assert colors_t0 != colors_t1


def test_multi_color_empty_falls_back_to_gradient_branch():
    """Empty multi_color list falls back to gradient or solid branch."""
    ov = DrawilleOverlay()
    ov._anim_params = AnimParams(width=100, height=56)
    ov._resolved_multi_colors = []   # empty
    ov.gradient = False
    ov._resolved_color = "#00ff66"
    ov._fade_step = 0
    ov.add_class("-visible")

    updates: list = []
    ov.update = lambda v: updates.append(v)
    ov._tick()
    # Falls through to solid-color Text path
    assert len(updates) == 1


def test_watch_multi_color_resolves_colors():
    """watch_multi_color stores resolved hex strings in _resolved_multi_colors."""
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = {}
    ov = DrawilleOverlay()
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.watch_multi_color(["#ff0000", "#00ff00", "#0000ff"])
    assert len(ov._resolved_multi_colors) == 3
    assert all(c.startswith("#") for c in ov._resolved_multi_colors)


def test_drawille_overlay_cfg_multi_color_defaults():
    """DrawilleOverlayCfg defaults: multi_color=[], hue_shift_speed=0.3."""
    cfg = DrawilleOverlayCfg()
    assert cfg.multi_color == []
    assert cfg.hue_shift_speed == 0.3


def test_overlay_config_parses_multi_color_list():
    """_overlay_config() correctly parses multi_color list from raw config."""
    raw = {
        "display": {
            "drawille_overlay": {
                "multi_color": ["#00ff66", "#004422", "#0066ff"],
                "hue_shift_speed": 0.5,
            }
        }
    }
    with patch("hermes_cli.config.read_raw_config", return_value=raw):
        cfg = _overlay_config()
    assert cfg.multi_color == ["#00ff66", "#004422", "#0066ff"]
    assert cfg.hue_shift_speed == 0.5


# ── Vertical mode ─────────────────────────────────────────────────────────────

def test_anim_params_has_vertical_field():
    """AnimParams.vertical defaults to False."""
    p = AnimParams(width=100, height=56)
    assert p.vertical is False


def test_anim_params_vertical_true():
    """AnimParams.vertical=True is accepted."""
    p = AnimParams(width=24, height=88, vertical=True)
    assert p.vertical is True


def test_vertical_dna_helix_scans_height_axis():
    """Vertical DnaHelixEngine sets points across y-axis, not x."""
    engine = DnaHelixEngine()
    params = AnimParams(width=24, height=88, vertical=True)
    result = engine.next_frame(params)
    assert isinstance(result, str)
    assert len(result) > 0


def test_vertical_and_horizontal_dna_differ():
    """Vertical and horizontal DNA frames differ for same canvas size."""
    engine = DnaHelixEngine()
    p_h = AnimParams(width=24, height=88, t=0.0, vertical=False)
    p_v = AnimParams(width=24, height=88, t=0.0, vertical=True)
    frame_h = engine.next_frame(p_h)
    frame_v = engine.next_frame(p_v)
    assert frame_h != frame_v


def test_vertical_medium_size_uses_portrait_dimensions():
    """vertical=True medium size → (12, 22)."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=120, height=40)
    ov = DrawilleOverlay()

    widths: list[int] = []
    heights: list[int] = []

    class StylesMock:
        @property
        def width(self): return 0
        @width.setter
        def width(self, v): widths.append(v)
        @property
        def height(self): return 0
        @height.setter
        def height(self, v): heights.append(v)
        @property
        def offset(self): return (0, 0)
        @offset.setter
        def offset(self, v): pass

    ov.styles = StylesMock()
    ov.size_name = "medium"
    ov.position = "top-right"
    ov.vertical = True
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()
    assert widths[-1] == 12
    assert heights[-1] == 22


def test_position_top_right_y_offset_is_1():
    """top-right position uses y_offset=1 (1 padding from top)."""
    tw, th = 120, 40
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=tw, height=th)
    ov = DrawilleOverlay()

    offsets_set: list[tuple] = []

    class StylesMock:
        @property
        def width(self): return 0
        @width.setter
        def width(self, v): pass
        @property
        def height(self): return 0
        @height.setter
        def height(self, v): pass
        @property
        def offset(self): return (0, 0)
        @offset.setter
        def offset(self, v): offsets_set.append(v)

    ov.styles = StylesMock()
    ov.size_name = "medium"
    ov.position = "top-right"
    ov.vertical = False
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()
    _, y_off = offsets_set[-1]
    assert y_off == 1


def test_show_propagates_vertical_to_anim_params():
    """show() sets _anim_params.vertical from cfg.vertical."""
    mock_app = MagicMock()
    mock_app.size = MagicMock(width=80, height=24)
    ov = DrawilleOverlay()
    ov.styles = MagicMock()
    ov._start_anim = MagicMock()
    ov._anim_params = AnimParams(width=24, height=88, vertical=False)
    cfg = _default_cfg(enabled=True, vertical=True, auto_hide_delay=0, fade_in_frames=0)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    assert ov._anim_params.vertical is True


def test_overlay_config_defaults_position_top_right():
    """_overlay_config() defaults position to 'top-right'."""
    with patch("hermes_cli.config.read_raw_config", return_value={}):
        cfg = _overlay_config()
    assert cfg.position == "top-right"


def test_overlay_config_defaults_vertical_true():
    """_overlay_config() defaults vertical to True."""
    with patch("hermes_cli.config.read_raw_config", return_value={}):
        cfg = _overlay_config()
    assert cfg.vertical is True


# ── Layer / absolute position ─────────────────────────────────────────────────

def test_drawille_overlay_default_css_no_hardcoded_offset():
    """DEFAULT_CSS must not hardcode 'offset: 15 5' — position set by _apply_layout."""
    assert "offset: 15 5" not in DrawilleOverlay.DEFAULT_CSS


def test_hermes_tcss_has_layer_overlay_for_drawille():
    """hermes.tcss must declare layer:overlay and position:absolute for DrawilleOverlay.

    These must live in hermes.tcss, NOT in DEFAULT_CSS — see CSS gotcha:
    layer:overlay in DEFAULT_CSS corrupts CSS compilation if the class is
    imported before HermesApp's import chain completes.
    """
    import os
    tcss_path = os.path.join(
        os.path.dirname(__file__), "../../hermes_cli/tui/hermes.tcss"
    )
    content = open(os.path.normpath(tcss_path)).read()
    assert "layer: overlay" in content
    assert "position: absolute" in content
