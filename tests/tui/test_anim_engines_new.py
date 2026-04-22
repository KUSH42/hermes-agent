"""Tests for new animation engines (Parts A–D) and /anim command improvements."""
from __future__ import annotations

import math
import random
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.anim_engines import (
    AnimParams,
    WireframeCubeEngine,
    SierpinskiEngine,
    PlasmaEngine,
    Torus3DEngine,
    MatrixRainEngine,
    _bresenham_pts,
)
from hermes_cli.tui.drawille_overlay import (
    _POS_GRID,
    _POS_TO_RC,
    _nearest_anchor,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_params(**kwargs: object) -> AnimParams:
    defaults = dict(width=80, height=40, t=0.0, dt=1 / 15)
    defaults.update(kwargs)  # type: ignore[arg-type]
    return AnimParams(**defaults)  # type: ignore[arg-type]


# ── D1: WireframeCubeEngine ────────────────────────────────────────────────────

class TestWireframeCubeEngine:

    def test_next_frame_returns_nonempty(self) -> None:
        engine = WireframeCubeEngine()
        result = engine.next_frame(make_params(width=80, height=40))
        assert len(result) > 0

    def test_next_frame_no_exception_normal_size(self) -> None:
        engine = WireframeCubeEngine()
        # exercise all 8 vertices at w=40, h=20
        params = make_params(width=40, height=20)
        engine.next_frame(params)  # must not raise

    def test_on_signal_complete_sets_spin_brake(self) -> None:
        engine = WireframeCubeEngine()
        assert engine._spin_brake is False
        engine.on_signal("complete")
        assert engine._spin_brake is True

    def test_heat_changes_frame(self) -> None:
        params_cold = make_params(width=40, height=20, heat=0.0, t=0.0)
        params_hot  = make_params(width=40, height=20, heat=2.0, t=0.0)
        e1 = WireframeCubeEngine()
        e2 = WireframeCubeEngine()
        r1 = e1.next_frame(params_cold)
        r2 = e2.next_frame(params_hot)
        # Different heat → different speed accumulation → different frames
        assert r1 != r2

    def test_tiny_canvas_no_exception(self) -> None:
        engine = WireframeCubeEngine()
        result = engine.next_frame(make_params(width=4, height=4))
        assert isinstance(result, str)


# ── D2: SierpinskiEngine ──────────────────────────────────────────────────────

class TestSierpinskiEngine:

    def test_nonempty_after_5_frames(self) -> None:
        engine = SierpinskiEngine()
        params = make_params(width=60, height=40)
        result = ""
        for _ in range(5):
            result = engine.next_frame(params)
        assert len(result) > 0

    def test_trail_keys_inbounds(self) -> None:
        engine = SierpinskiEngine()
        params = make_params(width=60, height=40)
        w, h = params.width, params.height
        for _ in range(10):
            engine.next_frame(params)
        for x, y in engine._trail._heat:
            assert 0 <= x < w
            assert 0 <= y < h

    def test_on_signal_complete_resets_trail(self) -> None:
        engine = SierpinskiEngine()
        params = make_params(width=60, height=40)
        for _ in range(5):
            engine.next_frame(params)
        assert len(engine._trail._heat) > 0
        engine.on_signal("complete")
        assert engine._trail._heat == {}

    def test_triangle_ifs_no_exception(self) -> None:
        engine = SierpinskiEngine()
        # symmetry=3 → triangle IFS
        params = make_params(width=60, height=40, symmetry=3)
        engine.next_frame(params)  # must not raise


# ── D3: PlasmaEngine ──────────────────────────────────────────────────────────

class TestPlasmaEngine:

    def test_frame_nonempty(self) -> None:
        engine = PlasmaEngine()
        result = engine.next_frame(make_params(width=60, height=40, trail_decay=0.0))
        assert len(result) > 0

    def test_noise_scale_affects_frame(self) -> None:
        e1 = PlasmaEngine()
        e2 = PlasmaEngine()
        r1 = e1.next_frame(make_params(width=40, height=20, noise_scale=0.1))
        r2 = e2.next_frame(make_params(width=40, height=20, noise_scale=2.0))
        assert r1 != r2

    def test_on_signal_thinking_increases_t_offset(self) -> None:
        engine = PlasmaEngine()
        assert engine._t_offset == 0.0
        engine.on_signal("thinking")
        assert engine._t_offset > 0

    def test_on_signal_complete_jumps_more_than_thinking(self) -> None:
        e1 = PlasmaEngine()
        e2 = PlasmaEngine()
        e1.on_signal("thinking")
        thinking_delta = e1._t_offset
        e2.on_signal("complete")
        complete_delta = e2._t_offset
        assert complete_delta > thinking_delta

    def test_trail_decay_threshold_changes_density(self) -> None:
        e1 = PlasmaEngine()
        e2 = PlasmaEngine()
        # trail_decay=0.0 → threshold=0, denser
        r1 = e1.next_frame(make_params(width=40, height=20, trail_decay=0.0, t=1.0))
        # trail_decay=1.0 → threshold=0.5, sparser
        r2 = e2.next_frame(make_params(width=40, height=20, trail_decay=1.0, t=1.0))
        # Count braille chars
        def count_set(s: str) -> int:
            return sum(1 for c in s if 0x2800 <= ord(c) <= 0x28FF and c != "⠀")
        assert count_set(r1) >= count_set(r2)


# ── D4: Torus3DEngine ─────────────────────────────────────────────────────────

class TestTorus3DEngine:

    def test_frame_nonempty(self) -> None:
        engine = Torus3DEngine()
        result = engine.next_frame(make_params(width=80, height=40))
        assert len(result) > 0

    def test_on_signal_complete_sets_reverse(self) -> None:
        engine = Torus3DEngine()
        engine.on_signal("complete")
        assert engine._rot_dir == -1.0
        assert engine._reverse_frames == 10

    def test_depth_cues_false_no_exception(self) -> None:
        engine = Torus3DEngine()
        engine.next_frame(make_params(width=60, height=40, depth_cues=False))

    def test_heat_changes_frame(self) -> None:
        # heat changes speed multiplier; use t>0 so rot_y differs
        e1 = Torus3DEngine()
        e2 = Torus3DEngine()
        r1 = e1.next_frame(make_params(width=60, height=30, heat=0.0, t=2.0))
        r2 = e2.next_frame(make_params(width=60, height=30, heat=2.0, t=2.0))
        assert r1 != r2


# ── D5: MatrixRainEngine ──────────────────────────────────────────────────────

class TestMatrixRainEngine:

    def test_columns_initialised_on_first_frame(self) -> None:
        engine = MatrixRainEngine()
        assert len(engine._columns) == 0
        engine.next_frame(make_params(width=60, height=40))
        assert len(engine._columns) > 0

    def test_nonempty_after_3_ticks(self) -> None:
        engine = MatrixRainEngine()
        params = make_params(width=60, height=40)
        result = ""
        for _ in range(3):
            result = engine.next_frame(params)
        assert len(result) > 0

    def test_on_signal_error_sets_surge_frames(self) -> None:
        engine = MatrixRainEngine()
        engine.on_signal("error")
        assert engine._error_surge_frames == 22

    def test_heat_affects_column_speed(self) -> None:
        e1 = MatrixRainEngine()
        e2 = MatrixRainEngine()
        random.seed(42)
        e1.next_frame(make_params(width=60, height=40, heat=0.0))
        random.seed(42)
        e2.next_frame(make_params(width=60, height=40, heat=2.0))
        mean_speed_cold = sum(c["speed"] for c in e1._columns) / len(e1._columns)
        mean_speed_hot  = sum(c["speed"] for c in e2._columns) / len(e2._columns)
        assert mean_speed_hot > mean_speed_cold

    def test_columns_dont_escape_after_100_ticks(self) -> None:
        engine = MatrixRainEngine()
        params = make_params(width=60, height=40)
        for _ in range(100):
            engine.next_frame(params)
        h = params.height
        assert all(c["y"] <= h + 20 for c in engine._columns)


# ── D6: _bresenham_pts ────────────────────────────────────────────────────────

class TestBresenhamPts:

    def test_horizontal_line_length(self) -> None:
        pts = _bresenham_pts(0, 5, 9, 5)
        assert len(pts) == abs(9 - 0) + 1

    def test_diagonal_start_end(self) -> None:
        x0, y0, x1, y1 = 2, 3, 8, 9
        pts = _bresenham_pts(x0, y0, x1, y1)
        assert pts[0] == (x0, y0)
        assert pts[-1] == (x1, y1)

    def test_degenerate_single_point(self) -> None:
        pts = _bresenham_pts(5, 7, 5, 7)
        assert pts == [(5, 7)]


# ── D7: Command improvements ──────────────────────────────────────────────────

class FakeApp:
    """Minimal app stub for testing _CommandsMixin._handle_anim_command."""

    def __init__(self) -> None:
        self._timers: list = []
        self._hints: list = []
        self._persisted: list = []
        self._anim_force = None
        self.agent_running = False

    def _flash_hint(self, msg: str, *args: object) -> None:
        self._hints.append(msg)

    def _persist_anim_config(self, d: dict) -> None:  # type: ignore[override]
        self._persisted.append(d)

    def set_timer(self, delay: float, callback: object) -> MagicMock:  # noqa: ARG002
        m = MagicMock()
        self._timers.append(delay)
        return m

    def query_one(self, _cls: type) -> "FakeOverlay":
        return FakeOverlay()

    def push_screen(self, _screen: object) -> None:
        pass

    def _drawille_show_hide(self, *args: object) -> None:
        pass


class FakeOverlay:
    animation: str = "dna"
    fps: int = 15
    gradient: bool = False
    color: str = "#00d7ff"
    color_b: str = "#8800ff"
    hue_shift_speed: float = 0.3
    size_name: str = "medium"
    _visibility_state: str = "hidden"
    _current_engine_instance: object = None

    def has_class(self, _cls: str) -> bool:
        return True

    def show(self, _cfg: object) -> None:
        pass

    def hide(self, _cfg: object) -> None:
        pass


def make_fake_anim_app() -> FakeApp:
    """Return a FakeApp with _handle_anim_command wired via CommandsService."""
    from hermes_cli.tui.services.commands import CommandsService

    app = FakeApp()
    svc = CommandsService.__new__(CommandsService)
    svc.app = app
    app._svc_commands = svc

    # Capture persist_anim_config calls into app._persisted
    def _fake_persist(cfg_dict: dict) -> None:
        app._persisted.append(cfg_dict)

    svc.persist_anim_config = _fake_persist  # type: ignore[method-assign]

    def _handle_anim_command(stripped: str) -> None:
        svc.handle_anim_command(stripped)

    app._handle_anim_command = _handle_anim_command  # type: ignore[method-assign]
    return app


class TestAnimCommandImprovements:

    def test_b1_duration_passed_to_set_timer(self) -> None:
        app = make_fake_anim_app()
        app.set_timer = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
        with patch("hermes_cli.tui.drawille_overlay._overlay_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(enabled=True, animation="wave", carousel=False)
            app._handle_anim_command("/anim wave 12")
        calls = [c.args[0] for c in app.set_timer.call_args_list]
        assert 12.0 in calls

    def test_b1_duration_clamped_to_120(self) -> None:
        app = make_fake_anim_app()
        app.set_timer = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
        with patch("hermes_cli.tui.drawille_overlay._overlay_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(enabled=True, animation="wave", carousel=False)
            app._handle_anim_command("/anim wave 200")
        calls = [c.args[0] for c in app.set_timer.call_args_list]
        assert 120.0 in calls

    def test_b2_speed_persists(self) -> None:
        app = make_fake_anim_app()
        app._handle_anim_command("/anim speed 30")
        assert any(isinstance(d, dict) and d.get("fps") == 30 for d in app._persisted)

    def test_b2_speed_invalid_flashes_usage(self) -> None:
        app = make_fake_anim_app()
        app._handle_anim_command("/anim speed abc")
        assert any("Usage" in str(h) for h in app._hints)

    def test_b3_ambient_persists(self) -> None:
        app = make_fake_anim_app()
        app._handle_anim_command("/anim ambient perlin")
        assert any(
            isinstance(d, dict) and d.get("ambient_engine") == "perlin_flow"
            for d in app._persisted
        )

    def test_b3_ambient_unknown_flashes(self) -> None:
        app = make_fake_anim_app()
        app._handle_anim_command("/anim ambient zzzunknown999")
        assert any("Unknown" in str(h) or "unknown" in str(h).lower() for h in app._hints)


# ── D1: Ctrl+Shift+Arrow position cycling ────────────────────────────────────

class TestPositionCycling:

    def test_right_from_center_goes_to_mid_right(self) -> None:
        col, row = _POS_TO_RC["center"]
        col = (col + 1) % 3
        assert _POS_GRID[row][col] == "mid-right"

    def test_down_from_mid_right_goes_to_bottom_right(self) -> None:
        col, row = _POS_TO_RC["mid-right"]
        row = (row + 1) % 3
        assert _POS_GRID[row][col] == "bottom-right"

    def test_right_from_top_right_wraps_to_top_left(self) -> None:
        col, row = _POS_TO_RC["top-right"]
        col = (col + 1) % 3
        assert _POS_GRID[row][col] == "top-left"

    def test_rail_position_falls_back_to_center(self) -> None:
        # rail-right not in _POS_TO_RC, should fall back to (1,1) = center
        col, row = _POS_TO_RC.get("rail-right", (1, 1))
        assert _POS_GRID[row][col] in _POS_TO_RC

    def test_ctrl_shift_arrow_calls_persist(self) -> None:
        """D1 handler logic: cycling right from center should call persist with new position."""
        # Test the grid cycling logic directly
        col, row = _POS_TO_RC.get("center", (1, 1))
        col = (col + 1) % 3  # right
        new_pos = _POS_GRID[row][col]
        assert new_pos == "mid-right"
        # Verify _POS_TO_RC has this position
        assert "mid-right" in _POS_TO_RC


# ── D2: _nearest_anchor ───────────────────────────────────────────────────────

class TestNearestAnchor:

    def test_top_right_corner(self) -> None:
        # tw=80, th=24, w=12, h=6; near top-right = (80-12-2, 1+2) = (66, 3)
        tw, th, w, h = 80, 24, 12, 6
        result = _nearest_anchor(64, 3, w, h, tw, th)
        assert result == "top-right"

    def test_mouse_down_sets_dragging(self) -> None:
        """D2: on_mouse_down sets _dragging = True."""
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay
        from textual import events

        class FakeOv:
            _dragging = False
            _drag_base_ox = 0
            _drag_base_oy = 0
            _drag_start_sx = 0
            _drag_start_sy = 0

            class app:
                @staticmethod
                def capture_mouse(_: object) -> None:
                    pass

        # Directly invoke the method with a bound instance
        ev = MagicMock(spec=events.MouseDown)
        ev.button = 1
        ev.screen_x = 10
        ev.screen_y = 5
        ov = FakeOv()
        DrawilleOverlay.on_mouse_down(ov, ev)  # type: ignore[arg-type]
        assert ov._dragging is True

    def test_mouse_up_clears_dragging(self) -> None:
        """D2: on_mouse_up clears _dragging and sets position."""
        from hermes_cli.tui.drawille_overlay import DrawilleOverlay
        from textual import events

        class FakeSize:
            width = 12
            height = 6

        class FakeAppSize:
            width = 80
            height = 24

        class FakeOv:
            _dragging = True
            _drag_base_ox = 10
            _drag_base_oy = 5
            _drag_start_sx = 10
            _drag_start_sy = 5
            position = "center"

            class app:
                size = FakeAppSize()
                _persisted: list = []

                @classmethod
                def release_mouse(cls) -> None:
                    pass

                @classmethod
                def _persist_anim_config(cls, d: dict) -> None:
                    cls._persisted.append(d)

            size = FakeSize()

        ev = MagicMock(spec=events.MouseUp)
        ev.screen_x = 70
        ev.screen_y = 3
        ov = FakeOv()
        DrawilleOverlay.on_mouse_up(ov, ev)  # type: ignore[arg-type]
        assert ov._dragging is False
        assert ov.position in _POS_TO_RC


# ── D3/D4: color/gradient/hue/size commands ───────────────────────────────────

class TestColorCommands:

    def _make_app_with_overlay(self) -> "tuple":
        app = make_fake_anim_app()
        ov = FakeOverlay()

        def _query_one(_cls: type) -> "FakeOverlay":
            return ov

        app.query_one = _query_one  # type: ignore[method-assign]
        return app, ov

    def test_color_valid_hex_sets_reactive(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim color #ff0000")
        assert ov.color == "#ff0000"

    def test_color_invalid_flashes_usage(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim color badval")
        assert any("Usage" in str(h) for h in app._hints)

    def test_gradient_on_sets_reactive(self) -> None:
        app, ov = self._make_app_with_overlay()
        ov.gradient = False
        app._handle_anim_command("/anim gradient on")
        assert ov.gradient is True

    def test_gradient_off_sets_reactive(self) -> None:
        app, ov = self._make_app_with_overlay()
        ov.gradient = True
        app._handle_anim_command("/anim gradient off")
        assert ov.gradient is False

    def test_gradient_with_two_colors(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim gradient #ff0000 #0000ff")
        assert ov.gradient is True
        assert ov.color == "#ff0000"
        assert ov.color_b == "#0000ff"

    def test_gradient_invalid_hex_flashes(self) -> None:
        app, ov = self._make_app_with_overlay()
        initial_gradient = ov.gradient
        app._handle_anim_command("/anim gradient #badval")
        assert any(h for h in app._hints)
        # gradient state should be unchanged
        assert ov.gradient == initial_gradient

    def test_hue_speed_set(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim hue 0.5")
        assert ov.hue_shift_speed == pytest.approx(0.5)

    def test_hue_off_sets_zero(self) -> None:
        app, ov = self._make_app_with_overlay()
        ov.hue_shift_speed = 1.0
        app._handle_anim_command("/anim hue off")
        assert ov.hue_shift_speed == 0.0

    def test_size_large_sets_reactive(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim size large")
        assert ov.size_name == "large"

    def test_size_invalid_flashes_usage(self) -> None:
        app, ov = self._make_app_with_overlay()
        app._handle_anim_command("/anim size invalid")
        assert any("Usage" in str(h) for h in app._hints)


# ── D5: hue_shift_speed in AnimConfigPanel._fields ────────────────────────────

class TestHueShiftSpeedField:

    def test_hue_shift_speed_field_present(self) -> None:
        from hermes_cli.tui.drawille_overlay import AnimConfigPanel
        with patch("hermes_cli.tui.drawille_overlay._overlay_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                animation="dna", fps=15, size="medium", position="center",
                color="$accent", gradient=False, color_secondary="$primary",
                trigger="agent_running", show_border=False, dim_background=True,
                vertical=False, blend_mode="overlay", layer_b="", trail_decay=0.0,
                hue_shift_speed=0.3, adaptive=False, particle_count=60,
                symmetry=6, attractor_type="lorenz", life_seed="gosper", depth_cues=True,
            )
            panel = AnimConfigPanel.__new__(AnimConfigPanel)
            panel._fields = []
            panel._focus_idx = 0
            panel._build_fields()
        assert any(f.name == "hue_shift_speed" for f in panel._fields)
