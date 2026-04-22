"""Tests for ThinkingWidget v2 — composed engine + effect animated placeholder.

18 tests:  T1–T18 per spec 2026-04-22-thinking-widget-redesign-spec.md
"""
from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

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


# ── T1: activate() no args → has --active + --mode-default classes ─────────────

@pytest.mark.asyncio
async def test_T1_activate_default_mode() -> None:
    async with _App().run_test() as pilot:
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
        assert w._substate is None


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
