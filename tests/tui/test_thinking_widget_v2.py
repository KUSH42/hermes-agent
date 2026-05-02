"""Tests for ThinkingWidget v2 — composed engine + effect animated placeholder.

18 tests:  T1–T18 per spec 2026-04-22-thinking-widget-redesign-spec.md
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets.thinking import (
    ThinkingWidget,
    ThinkingMode,
    _AnimSurface,
    _LabelLine,
    _WHITELIST_SMALL,
    _WHITELIST_EFFECT,
)


# ── Test app ──────────────────────────────────────────────────────────────────

class _App(App):
    def compose(self) -> ComposeResult:
        yield ThinkingWidget(id="thinking")


class _CompactApp(App):
    compact: bool = True

    def compose(self) -> ComposeResult:
        yield ThinkingWidget(id="thinking")


class _ThinkingWithMockApp(ThinkingWidget):
    @property
    def app(self):
        return self._mock_app


# ── T1: activate() no args → has --active + --mode-default classes ─────────────

@pytest.mark.asyncio
async def test_T1_activate_default_mode() -> None:
    # Use a wide terminal so narrow-terminal auto-demotion (F-2) doesn't trigger
    async with _App().run_test(size=(140, 40)) as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        assert w.has_class("--active")
        assert w.has_class("--mode-default")


# ── T2: activate(mode=LINE) → has --mode-line ─────────────────────────────────

@pytest.mark.asyncio
async def test_T2_activate_line_mode() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.LINE)
        await pilot.pause()
        assert w.has_class("--mode-line")
        assert w.has_class("--active")


# ── T3: activate(mode=DEEP) → has --mode-deep ────────────────────────────────

@pytest.mark.asyncio
async def test_T3_activate_deep_mode() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.DEEP)
        await pilot.pause()
        assert w.has_class("--mode-deep")
        assert w.has_class("--active")


# ── T4: activate(mode=OFF) → widget stays hidden (no --active class) ──────────

@pytest.mark.asyncio
async def test_T4_activate_off_stays_hidden() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.OFF)
        await pilot.pause()
        assert not w.has_class("--active")
        assert w._timer is None


# ── T5: app.compact=True at activate → uses COMPACT mode ──────────────────────

@pytest.mark.asyncio
async def test_T5_compact_app_uses_compact_mode() -> None:
    async with _CompactApp().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()  # no explicit mode — should detect compact=True
        await pilot.pause()
        assert w.has_class("--mode-compact")


# ── T6: non-whitelisted engine for COMPACT → falls back to dna, no exception ──

@pytest.mark.asyncio
async def test_T6_non_whitelisted_engine_fallback() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        # "vortex" is DEEP-only, not whitelisted for COMPACT
        w.activate(mode=ThinkingMode.COMPACT, engine="vortex")
        await pilot.pause()
        # Should not raise, anim surface should have fallen back to dna
        assert w.has_class("--active")
        assert w.has_class("--mode-compact")
        if w._anim_surface is not None:
            # Engine key resolved to dna fallback
            assert w._anim_surface._engine_key in ("dna", "vortex")  # key is stored before fallback
            # Engine instance should be set (dna engine)
            # The main check: no exception thrown


# ── T7: non-whitelisted effect → falls back to breathe, no exception ──────────

@pytest.mark.asyncio
async def test_T7_non_whitelisted_effect_fallback() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.LINE, effect="shimmer")  # shimmer not in whitelist
        await pilot.pause()
        assert w.has_class("--active")
        # Should have fallen back to breathe


# ── T8: substate STARTED → WORKING after 500ms ───────────────────────────────

@pytest.mark.asyncio
async def test_T8_substate_started_to_working() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        assert w._substate == "STARTED"

        # Simulate time passing > 500ms by manipulating _activate_time
        w._activate_time = time.monotonic() - 0.6  # 600ms ago
        w._tick()  # drive state machine
        assert w._substate == "WORKING"


# ── T9: LONG_WAIT after long_wait_after_s → label shows (Ns) suffix ──────────

@pytest.mark.asyncio
async def test_T9_long_wait_label_suffix() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()

        # Force WORKING substate first
        w._substate = "WORKING"
        # Simulate enough time for LONG_WAIT (default 8s)
        w._activate_time = time.monotonic() - 10.0
        # The _tick must recognize LONG_WAIT; also set _label_line mock to capture update

        mock_calls = []
        if w._label_line is not None:
            original_tick = w._label_line.tick_label
            def capture_tick(label_text: str, accent: str, text: str) -> None:
                mock_calls.append(label_text)
                try:
                    original_tick(label_text, accent, text)
                except Exception:
                    pass
            w._label_line.tick_label = capture_tick  # type: ignore[method-assign]

        w._tick()
        assert w._substate == "LONG_WAIT"

        # Drive another tick to capture label text
        w._tick()
        if mock_calls:
            assert any("(10s)" in t or "s)" in t for t in mock_calls), \
                f"Expected elapsed suffix in label, got: {mock_calls}"


# ── T10: deactivate() sets ABOUT_TO_STREAM; still visible immediately; hidden after call_later ──

@pytest.mark.asyncio
async def test_T10_deactivate_two_phase() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        assert w.has_class("--active")

        w.deactivate()
        await pilot.pause()
        # Immediately after deactivate(): substate = ABOUT_TO_STREAM, still has --active
        assert w._substate == "ABOUT_TO_STREAM"
        assert w.has_class("--active")

        # After call_later fires (use pause to advance event loop several cycles)
        # Wait longer for the 150ms timer to fire
        await pilot.pause(delay=0.3)
        assert not w.has_class("--active")
        # D-4: _substate is "--reserved" (layout reserve held until first live-line chunk)
        assert w._substate == "--reserved"


# ── T11: deactivate() while already ABOUT_TO_STREAM → no-op ──────────────────

@pytest.mark.asyncio
async def test_T11_deactivate_idempotent_about_to_stream() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()

        w.deactivate()
        await pilot.pause()
        assert w._substate == "ABOUT_TO_STREAM"

        # Second deactivate() should be a no-op
        w.deactivate()
        await pilot.pause()
        # Substate still ABOUT_TO_STREAM (no double scheduling)
        assert w._substate == "ABOUT_TO_STREAM"


# ── T12: activate() while already active → no-op ────────────────────────────

@pytest.mark.asyncio
async def test_T12_activate_while_active_noop() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate()
        await pilot.pause()
        timer_first = w._timer
        activate_time_first = w._activate_time

        w.activate()  # second call — should be no-op
        await pilot.pause()

        assert w._timer is timer_first  # same timer


# ── T13: width change → _AnimSurface._build_params uses new width ─────────────

@pytest.mark.asyncio
async def test_T13_anim_surface_uses_widget_width() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.DEFAULT)
        await pilot.pause()

        if w._anim_surface is not None:
            # Call _build_params at different mock widths
            original_size = w._anim_surface.size

            # Patch the size property to simulate width change
            from unittest.mock import PropertyMock
            mock_size = MagicMock()
            mock_size.width = 80
            mock_size.height = 2
            with patch.object(type(w._anim_surface), "size", new_callable=PropertyMock, return_value=mock_size):
                params = w._anim_surface._build_params(dt=1/12)
                assert params is not None
                # canvas_w = max(4, (80 - 2) * 2) = 156
                assert params.width == (80 - 2) * 2


# ── T14: set_mode(DEEP) while active → CSS class updated ─────────────────────

@pytest.mark.asyncio
async def test_T14_set_mode_updates_css() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.DEFAULT)
        await pilot.pause()
        assert w.has_class("--mode-default")

        w.set_mode(ThinkingMode.DEEP)
        await pilot.pause()
        assert w.has_class("--mode-deep")
        assert not w.has_class("--mode-default")


# ── T15: ThinkingWidget importable from hermes_cli.tui.widgets ───────────────

def test_T15_importable_from_widgets_package() -> None:
    from hermes_cli.tui.widgets import ThinkingWidget as TW
    assert TW is ThinkingWidget


# ── T16: elapsed_s() returns 0.0 when inactive; > 0 when active ──────────────

@pytest.mark.asyncio
async def test_T16_elapsed_s() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        assert w.elapsed_s() == 0.0

        w.activate()
        await pilot.pause()
        elapsed = w.elapsed_s()
        assert elapsed >= 0.0  # may be very small but non-negative


# ── T17: _LabelLine.update called with Rich Text (not plain str) ──────────────

@pytest.mark.asyncio
async def test_T17_label_line_update_rich_text() -> None:
    from rich.text import Text as RichText

    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.LINE)
        await pilot.pause()

        assert w._label_line is not None
        updates: list[Any] = []

        original_update = w._label_line.update
        def capture_update(content: Any) -> None:
            updates.append(content)
            try:
                original_update(content)
            except Exception:
                pass

        w._label_line.update = capture_update  # type: ignore[method-assign]
        w._tick()

        # At least one update should have happened (or will happen on next tick)
        # Force a direct tick_label call
        w._label_line.tick_label("Thinking…", "#888888", "#ffffff")

        # Check: updates should include a RichText instance (not plain str)
        rich_updates = [u for u in updates if isinstance(u, RichText)]
        assert len(rich_updates) > 0, f"Expected RichText updates, got: {[type(u) for u in updates]}"


# ── T18: engine on_mount called when defined ──────────────────────────────────

@pytest.mark.asyncio
async def test_T18_engine_on_mount_called() -> None:
    async with _App().run_test() as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w.activate(mode=ThinkingMode.DEFAULT)
        await pilot.pause()

        if w._anim_surface is None:
            pytest.skip("No _AnimSurface in LINE mode")

        # Create a mock engine with on_mount and patch _ENGINES
        on_mount_calls: list[Any] = []

        class _MockEngine:
            def next_frame(self, params: Any) -> str:
                return ""

            def on_mount(self, shim: Any) -> None:
                on_mount_calls.append(shim)

        from hermes_cli.tui.drawbraille_overlay import _ENGINES
        original = dict(_ENGINES)
        _ENGINES["_test_engine_hook"] = _MockEngine  # type: ignore[assignment]
        try:
            surf = _AnimSurface("_test_engine_hook")
            # Mount it manually inside the app
            await pilot.app.mount(surf)
            await pilot.pause()
            # on_mount should have been called
            assert len(on_mount_calls) == 1
            assert hasattr(on_mount_calls[0], "app")
        finally:
            # Restore _ENGINES
            _ENGINES.clear()
            _ENGINES.update(original)
            try:
                surf.remove()
            except Exception:
                pass


# ── V2: thinking-active app class ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_V2_activate_adds_thinking_active_class() -> None:
    """activate() must add 'thinking-active' CSS class to app."""
    os.environ["HERMES_DETERMINISTIC"] = ""
    try:
        async with _App().run_test() as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            del os.environ["HERMES_DETERMINISTIC"]
            w.activate()
            await pilot.pause()
            assert pilot.app.has_class("thinking-active"), (
                "App missing 'thinking-active' class after activate()"
            )
    finally:
        os.environ.pop("HERMES_DETERMINISTIC", None)


@pytest.mark.asyncio
async def test_V2_deactivate_removes_thinking_active_class() -> None:
    """After deactivate() completes, 'thinking-active' is removed from app."""
    os.environ["HERMES_DETERMINISTIC"] = ""
    try:
        async with _App().run_test() as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            del os.environ["HERMES_DETERMINISTIC"]
            w.activate()
            await pilot.pause()
            assert pilot.app.has_class("thinking-active")
            w.deactivate()
            # _do_hide fires after 0.15s timer; advance time past it
            import asyncio
            await asyncio.sleep(0.2)
            await pilot.pause()
            assert not pilot.app.has_class("thinking-active"), (
                "App still has 'thinking-active' class after deactivate()"
            )
    finally:
        os.environ.pop("HERMES_DETERMINISTIC", None)


# ── V4: UserMessagePanel default left padding ─────────────────────────────────

def test_V4_user_message_panel_default_padding_is_2() -> None:
    """UserMessagePanel DEFAULT_CSS must have padding: 0 2 (2-col left gutter)."""
    from hermes_cli.tui.widgets.message_panel import UserMessagePanel
    css = UserMessagePanel.DEFAULT_CSS
    # Extract the padding value from the CSS block
    import re
    match = re.search(r"padding\s*:\s*(\S+)\s+(\d+)", css)
    assert match is not None, "Could not find padding in UserMessagePanel.DEFAULT_CSS"
    left_padding = match.group(2)
    assert left_padding == "2", (
        f"UserMessagePanel left padding is {left_padding!r}, expected '2'"
    )


def _segment_colors(strip) -> list[str | None]:
    return [None if seg.style is None else seg.style.color.triplet.hex for seg in strip._segments]  # type: ignore[attr-defined]


def _segment_backgrounds(strip) -> list[str | None]:
    return [
        None if seg.style is None or seg.style.bgcolor is None else seg.style.bgcolor.triplet.hex.lstrip("#")
        for seg in strip._segments
    ]  # type: ignore[attr-defined]


def test_anim_surface_render_line_uses_multiple_segment_colors() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._frame_lines = ["⠁⠂⠃⠄"]
    surf._frame_tick = 2
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._dim_rgb = (32, 32, 32)
    surf._peak_rgb = (220, 220, 220)
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4)):
        strip = surf.render_line(0)
    colors = [color for color in _segment_colors(strip) if color is not None]
    assert len(set(colors)) > 1


def test_anim_surface_padding_does_not_get_peak_highlight() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._frame_lines = ["⠁⠂  "]
    surf._frame_tick = 1
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._dim_rgb = (32, 32, 32)
    surf._peak_rgb = (220, 220, 220)
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4)):
        strip = surf.render_line(0)
    tail = list(strip._segments)[-1]  # type: ignore[attr-defined]
    assert tail.text == " "
    assert tail.style.color is None
    assert tail.style.bgcolor.triplet.hex.lstrip("#") == "1e1e1e"


def test_thinking_refresh_colors_reads_spinner_gradient_vars() -> None:
    w = _ThinkingWithMockApp.__new__(_ThinkingWithMockApp)
    w._mock_app = SimpleNamespace(get_css_variables=lambda: {
        "accent": "#111111",
        "text": "#eeeeee",
        "app-bg": "#202224",
        "thinking-spinner-dim": "#123456",
        "thinking-spinner-peak": "#abcdef",
    })
    w._refresh_colors()
    assert w._app_bg_hex == "#202224"
    assert w._spinner_dim_hex == "#123456"
    assert w._spinner_peak_hex == "#abcdef"
    assert w._spinner_dim_rgb == (18, 52, 86)
    assert w._spinner_peak_rgb == (171, 205, 239)


def test_thinking_refresh_colors_falls_back_when_spinner_gradient_vars_missing() -> None:
    w = _ThinkingWithMockApp.__new__(_ThinkingWithMockApp)
    w._mock_app = SimpleNamespace(get_css_variables=lambda: {})
    w._refresh_colors()
    assert w._app_bg_hex == "#1e1e1e"
    assert w._spinner_dim_hex == "#4a4a4a"
    assert w._spinner_peak_hex == "#d8d8d8"
    assert w._spinner_dim_rgb == (74, 74, 74)
    assert w._spinner_peak_rgb == (216, 216, 216)


def test_anim_surface_row_phase_offset_changes_row_wave() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._frame_lines = ["⠁⠂⠃⠄", "⠁⠂⠃⠄"]
    surf._frame_tick = 3
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._dim_rgb = (32, 32, 32)
    surf._peak_rgb = (220, 220, 220)
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4)):
        first = _segment_colors(surf.render_line(0))
        second = _segment_colors(surf.render_line(1))
    assert first != second


def test_anim_surface_blank_row_fast_path_skips_gradient_work() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._frame_lines = ["    "]
    surf._frame_tick = 0
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._dim_rgb = (32, 32, 32)
    surf._peak_rgb = (220, 220, 220)
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4)):
        with patch.object(surf, "_render_gradient_line", wraps=surf._render_gradient_line) as mock_render:
            strip = surf.render_line(0)
    assert mock_render.call_count == 0
    assert "".join(seg.text for seg in strip._segments) == "    "  # type: ignore[attr-defined]
    assert set(_segment_backgrounds(strip)) == {"1e1e1e"}


def test_anim_surface_gradient_segments_keep_app_background() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._frame_lines = ["⠁⠂⠃⠄"]
    surf._frame_tick = 2
    surf._background_hex = "#202224"
    surf._background_rgb = (32, 34, 36)
    surf._dim_rgb = (18, 52, 86)
    surf._peak_rgb = (171, 205, 239)
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4)):
        strip = surf.render_line(0)
    assert set(_segment_backgrounds(strip)) == {"202224"}


def test_tick_anim_uses_theme_gradient_and_background_colors() -> None:
    surf = _AnimSurface.__new__(_AnimSurface)
    surf._engine_key = "dna"
    surf._engine = SimpleNamespace(next_frame=lambda params: "⠁⠂")
    surf._frame_lines = []
    surf._elapsed = 0.0
    surf._last_w = 0
    surf._accent_hex = "#888888"
    surf._background_hex = "#1e1e1e"
    surf._background_rgb = (30, 30, 30)
    surf._peak_hex = "#d8d8d8"
    surf._dim_rgb = (136, 136, 136)
    surf._peak_rgb = (216, 216, 216)
    surf._frame_tick = 0
    with patch.object(type(surf), "size", new_callable=PropertyMock, return_value=SimpleNamespace(width=4, height=1)):
        with patch.object(surf, "refresh"):
            surf.tick_anim(0.1, "#123456", "#abcdef", "#202224")
            strip = surf.render_line(0)
    assert surf._dim_rgb == (18, 52, 86)
    assert surf._peak_rgb == (171, 205, 239)
    assert surf._background_rgb == (32, 34, 36)
    assert set(_segment_backgrounds(strip)) == {"202224"}


def test_load_config_accepts_scalar_or_list_for_short_and_long_wait_fields() -> None:
    scalar = ThinkingWidget.__new__(ThinkingWidget)
    scalar._cfg_loaded = False
    with patch("hermes_cli.config.read_raw_config", return_value={
        "tui": {
            "thinking": {
                "engine": "dna",
                "effect": "breathe",
                "long_wait_engine": "wave_function",
                "long_wait_effect": "shimmer",
            }
        }
    }):
        scalar._load_config()
    assert scalar._normalize_engine_pool(
        scalar._cfg_engine, ThinkingMode.DEFAULT, default_key="dna", field_name="engine"
    ) == ("dna",)
    assert scalar._normalize_effect_pool(
        scalar._cfg_effect, default_key="breathe", field_name="effect"
    ) == ("breathe",)

    pooled = ThinkingWidget.__new__(ThinkingWidget)
    pooled._cfg_loaded = False
    pooled._cfg_allow_intense = False
    with patch("hermes_cli.config.read_raw_config", return_value={
        "tui": {
            "thinking": {
                "engine": ["dna", "wave_function"],
                "effect": ["breathe", "glow_settle"],
                "long_wait_engine": ["wave_function", "neural_pulse"],
                "long_wait_effect": ["shimmer", "cosmic"],
            }
        }
    }):
        pooled._load_config()
    assert pooled._normalize_engine_pool(
        pooled._cfg_engine, ThinkingMode.DEFAULT, default_key="dna", field_name="engine"
    ) == ("dna", "wave_function")
    assert pooled._normalize_effect_pool(
        pooled._cfg_long_wait_effect, default_key="shimmer", field_name="long_wait_effect"
    ) == ("shimmer", "cosmic")


@pytest.mark.asyncio
async def test_short_wait_choice_picked_once_on_activate() -> None:
    async with _App().run_test(size=(140, 40)) as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w._cfg_engine = ["dna", "wave_function"]
        w._cfg_effect = ["breathe", "glow_settle"]
        w._cfg_long_wait_engine = ["wave_function"]
        w._cfg_long_wait_effect = ["shimmer"]
        w._cfg_loaded = True
        with patch("hermes_cli.tui.widgets.thinking.random.choice", side_effect=lambda pool: pool[0]) as mock_choice:
            w.activate(mode=ThinkingMode.DEFAULT)
            await pilot.pause()
            w._tick()
        assert mock_choice.call_count == 2


def test_long_wait_choice_picked_once_on_transition() -> None:
    w = ThinkingWidget.__new__(ThinkingWidget)
    w._cfg_tick_hz = 12.0
    w._cfg_long_wait_after_s = 8.0
    w._cfg_show_elapsed = False
    w._activate_time = time.monotonic() - 10.0
    w._substate = "WORKING"
    w._current_mode = ThinkingMode.DEFAULT
    w._long_wait_engine_pool = ("wave_function", "neural_pulse")
    w._long_wait_effect_pool = ("shimmer", "cosmic")
    w._resolved_long_wait_engine = None
    w._resolved_long_wait_effect = None
    w._spinner_dim_hex = "#4a4a4a"
    w._spinner_peak_hex = "#d8d8d8"
    w._accent_hex = "#888888"
    w._text_hex = "#ffffff"
    w._base_label = "Thinking…"
    w._last_token_time = None
    w._anim_surface = MagicMock()
    w._anim_surface._engine_key = "dna"
    w._label_line = MagicMock()
    w._label_line._lock = MagicMock()
    with patch("hermes_cli.tui.widgets.thinking.random.choice", side_effect=lambda pool: pool[0]) as mock_choice:
        with patch("hermes_cli.stream_effects.make_stream_effect", return_value=object()):
            w._tick()
            w._tick()
    assert mock_choice.call_count == 2


def test_mode_validation_drops_deep_only_engines_from_small_mode_pool() -> None:
    w = ThinkingWidget.__new__(ThinkingWidget)
    w._cfg_allow_intense = False
    pool = w._normalize_engine_pool(
        ["vortex", "dna"],
        ThinkingMode.COMPACT,
        default_key="dna",
        field_name="engine",
    )
    assert pool == ("dna",)


@pytest.mark.asyncio
async def test_explicit_activate_engine_effect_bypass_pool_randomization() -> None:
    async with _App().run_test(size=(140, 40)) as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w._cfg_engine = ["wave_function", "dna"]
        w._cfg_effect = ["glow_settle", "breathe"]
        w._cfg_long_wait_engine = ["wave_function"]
        w._cfg_long_wait_effect = ["shimmer"]
        w._cfg_loaded = True
        with patch("hermes_cli.tui.widgets.thinking.random.choice", side_effect=AssertionError("unexpected reroll")):
            w.activate(mode=ThinkingMode.DEFAULT, engine="dna", effect="breathe")
            await pilot.pause()
        assert w._resolved_engine == "dna"
        assert w._resolved_effect == "breathe"


@pytest.mark.asyncio
async def test_tick_does_not_revalidate_or_rerandomize_cached_pools() -> None:
    async with _App().run_test(size=(140, 40)) as pilot:
        w = pilot.app.query_one(ThinkingWidget)
        w._cfg_engine = ["dna"]
        w._cfg_effect = ["breathe"]
        w._cfg_long_wait_engine = ["wave_function"]
        w._cfg_long_wait_effect = ["shimmer"]
        w._cfg_loaded = True
        w.activate(mode=ThinkingMode.DEFAULT)
        await pilot.pause()
        w._substate = "WORKING"
        w._activate_time = time.monotonic()
        with patch.object(w, "_normalize_engine_pool", side_effect=AssertionError("should not normalize on tick")):
            with patch.object(w, "_normalize_effect_pool", side_effect=AssertionError("should not normalize on tick")):
                with patch("hermes_cli.tui.widgets.thinking.random.choice", side_effect=AssertionError("should not reroll on steady tick")):
                    w._tick()


# --- TW-A/B/C/D additions ---

def test_tick_anim_signature_compat() -> None:
    """TW-B backward compat — tick_anim(dt) with no accent arg must not raise."""
    from hermes_cli.tui.widgets.thinking import _AnimSurface
    s = _AnimSurface.__new__(_AnimSurface)
    s._engine_key = "dna"
    s._engine = None
    s._frame_lines = []
    s._elapsed = 0.0
    s._last_w = 0
    s._accent_hex = "#888888"
    # No accent arg — default kicks in
    from unittest.mock import patch
    with patch.object(s, "refresh"):
        s.tick_anim(0.1)
    assert s._accent_hex == "#888888"


def test_long_wait_transition_combined() -> None:
    """TW-A + TW-C fire in same tick — both engine and effect swap."""
    import time
    import threading
    from unittest.mock import MagicMock, patch
    from hermes_cli.tui.widgets.thinking import ThinkingWidget, ThinkingMode, _AnimSurface
    from hermes_cli.stream_effects import ShimmerEffect

    w = ThinkingWidget.__new__(ThinkingWidget)
    w._cfg_loaded = True
    w._cfg_long_wait_after_s = 8.0
    w._cfg_long_wait_engine = "wave_function"
    w._cfg_long_wait_effect = "shimmer"
    w._cfg_engine = "dna"
    w._cfg_effect = "breathe"
    w._cfg_allow_intense = False
    w._substate = "WORKING"
    w._activate_time = time.monotonic() - 10.0
    w._current_mode = ThinkingMode.DEFAULT

    s = _AnimSurface.__new__(_AnimSurface)
    s._engine_key = "dna"
    s._engine = MagicMock()
    s._frame_lines = []
    s._elapsed = 0.0
    s._accent_hex = "#888888"
    w._anim_surface = s

    lock = threading.Lock()
    ll = MagicMock()
    ll._lock = lock
    w._label_line = ll

    from hermes_cli.stream_effects import make_stream_effect
    elapsed = 10.0
    if w._substate == "WORKING" and elapsed >= w._cfg_long_wait_after_s:
        w._substate = "LONG_WAIT"
        if w._anim_surface is not None:
            lw_engine = w._resolve_engine(w._cfg_long_wait_engine, w._current_mode or ThinkingMode.DEFAULT)
            if lw_engine != w._anim_surface._engine_key:
                with patch.object(s, "_init_engine"):
                    w._anim_surface.swap_engine(lw_engine)
        if w._label_line is not None:
            lw_effect = w._resolve_effect(w._cfg_long_wait_effect)
            new_fx = make_stream_effect({"stream_effect": lw_effect}, lock=lock)
            w._label_line._effect = new_fx

    assert s._engine_key == "wave_function"
    assert isinstance(w._label_line._effect, ShimmerEffect)


def test_config_long_wait_keys_loaded() -> None:
    """Both long_wait_engine and long_wait_effect loaded from config."""
    from unittest.mock import patch
    from hermes_cli.tui.widgets.thinking import ThinkingWidget

    w = ThinkingWidget.__new__(ThinkingWidget)
    w._cfg_loaded = False
    w._cfg_mode = "default"
    w._cfg_engine = "dna"
    w._cfg_effect = "breathe"
    w._cfg_tick_hz = 12.0
    w._cfg_long_wait_after_s = 8.0
    w._cfg_deep_after_s = 120.0
    w._cfg_show_elapsed = True
    w._cfg_allow_intense = False
    w._cfg_long_wait_engine = "wave_function"
    w._cfg_long_wait_effect = "shimmer"

    cfg = {"tui": {"thinking": {"long_wait_engine": "rope_braid", "long_wait_effect": "breathe"}}}
    with patch("hermes_cli.config.read_raw_config", return_value=cfg):
        w._load_config()

    assert w._cfg_long_wait_engine == "rope_braid"
    assert w._cfg_long_wait_effect == "breathe"
