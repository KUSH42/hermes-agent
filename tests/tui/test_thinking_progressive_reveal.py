"""TW-PR: ThinkingWidget progressive reveal — 14 tests.

Spec: /home/xush/.hermes/tw-progressive-reveal-spec.md
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.widgets.thinking import ThinkingWidget, ThinkingMode


# ── Shared test app ────────────────────────────────────────────────────────────

class _App(App):
    def compose(self) -> ComposeResult:
        yield ThinkingWidget(id="thinking")


# ══════════════════════════════════════════════════════════════════════════════
# TestLoadConfig  (TW-PR-1 — 2 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadConfig:

    def _make_widget(self) -> ThinkingWidget:
        w = object.__new__(ThinkingWidget)
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
        w._cfg_progressive_reveal = True
        w._anim_surface = None
        w._label_line = None
        return w

    def test_load_config_progressive_reveal_true(self):
        w = self._make_widget()
        raw = {"tui": {"thinking": {"progressive_reveal": True}}}
        with patch("hermes_cli.config.read_raw_config", return_value=raw):
            # Reset so _load_config actually runs
            w._cfg_loaded = False
            w._load_config()
        assert w._cfg_progressive_reveal is True

    def test_load_config_progressive_reveal_false(self):
        w = self._make_widget()
        raw = {"tui": {"thinking": {"progressive_reveal": False}}}
        with patch("hermes_cli.config.read_raw_config", return_value=raw):
            w._cfg_loaded = False
            w._load_config()
        assert w._cfg_progressive_reveal is False


# ══════════════════════════════════════════════════════════════════════════════
# TestActivateInitialMode  (TW-PR-2 — 4 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestActivateInitialMode:

    @pytest.mark.asyncio
    async def test_activate_progressive_ceiling_default(self):
        """reveal=True, ceiling=DEFAULT → starts at --mode-compact."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.DEFAULT)
            await pilot.pause()
            assert w.has_class("--mode-compact")
            assert not w.has_class("--mode-default")
            assert w._ceiling_mode == ThinkingMode.DEFAULT

    @pytest.mark.asyncio
    async def test_activate_progressive_ceiling_deep(self):
        """reveal=True, ceiling=DEEP → starts at --mode-compact."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.DEEP)
            await pilot.pause()
            assert w.has_class("--mode-compact")
            assert not w.has_class("--mode-deep")
            assert w._ceiling_mode == ThinkingMode.DEEP

    @pytest.mark.asyncio
    async def test_activate_reveal_disabled_default(self):
        """reveal=False, ceiling=DEFAULT → --mode-default applied immediately."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = False
            w.activate(mode=ThinkingMode.DEFAULT)
            await pilot.pause()
            assert w.has_class("--mode-default")
            assert not w.has_class("--mode-compact")

    @pytest.mark.asyncio
    async def test_activate_line_never_expands(self):
        """LINE ceiling is never subject to progressive reveal; _anim_surface is None."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.LINE)
            await pilot.pause()
            assert w.has_class("--mode-line")
            assert w._anim_surface is None


# ══════════════════════════════════════════════════════════════════════════════
# TestStartedToWorking  (TW-PR-3 — 3 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestStartedToWorking:

    @pytest.mark.asyncio
    async def test_tick_started_to_working_expands_default(self):
        """ceiling=DEFAULT, reveal=True, elapsed=0.6 → --mode-default after tick."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.DEFAULT)
            await pilot.pause()
            assert w.has_class("--mode-compact")

            # Simulate 0.6s elapsed → STARTED→WORKING fires
            w._activate_time = time.monotonic() - 0.6
            w._tick()
            await pilot.pause()

            assert w._substate == "WORKING"
            assert w.has_class("--mode-default")
            assert not w.has_class("--mode-compact")

    @pytest.mark.asyncio
    async def test_tick_started_to_working_expands_deep_ceiling(self):
        """ceiling=DEEP, reveal=True, elapsed=0.6 → --mode-default (not DEEP yet)."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.DEEP)
            await pilot.pause()
            assert w.has_class("--mode-compact")

            w._activate_time = time.monotonic() - 0.6
            w._tick()
            await pilot.pause()

            assert w._substate == "WORKING"
            assert w.has_class("--mode-default")
            assert not w.has_class("--mode-compact")
            assert not w.has_class("--mode-deep")

    @pytest.mark.asyncio
    async def test_tick_started_to_working_compact_ceiling_no_expand(self):
        """ceiling=COMPACT, reveal=True, elapsed=0.6 → stays --mode-compact."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w.activate(mode=ThinkingMode.COMPACT)
            await pilot.pause()
            assert w.has_class("--mode-compact")

            w._activate_time = time.monotonic() - 0.6
            w._tick()
            await pilot.pause()

            assert w._substate == "WORKING"
            assert w.has_class("--mode-compact")
            assert not w.has_class("--mode-default")


# ══════════════════════════════════════════════════════════════════════════════
# TestDeepExpansion  (TW-PR-4 — 5 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestDeepExpansion:

    def test_a4_bug_fixed_deep_resolves_without_substate_start(self):
        """_resolve_mode() with config DEEP and no _substate_start → returns DEEP."""
        w = object.__new__(ThinkingWidget)
        w._cfg_loaded = True
        w._cfg_mode = "deep"
        w._cfg_engine = "dna"
        w._cfg_effect = "breathe"
        w._cfg_tick_hz = 12.0
        w._cfg_long_wait_after_s = 8.0
        w._cfg_deep_after_s = 120.0
        w._cfg_show_elapsed = True
        w._cfg_allow_intense = False
        w._cfg_long_wait_engine = "wave_function"
        w._cfg_long_wait_effect = "shimmer"
        w._cfg_progressive_reveal = True
        # No _substate_start set — old A4 gate would have returned COMPACT here

        mock_app = MagicMock()
        mock_app.has_class.return_value = False
        mock_app.compact = False
        mock_app.size.width = 140

        with patch.object(type(w), "app", new_callable=lambda: property(lambda self: mock_app)):
            result = w._resolve_mode(None)

        assert result == ThinkingMode.DEEP

    @pytest.mark.asyncio
    async def test_tick_deep_expansion_fires_at_deep_after_s(self):
        """ceiling=DEEP, reveal=True, substate=LONG_WAIT, elapsed=121 → set_mode DEEP."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w._cfg_deep_after_s = 120.0
            w.activate(mode=ThinkingMode.DEEP)
            await pilot.pause()

            # Fast-forward: put widget into LONG_WAIT state with 121s elapsed
            w._substate = "LONG_WAIT"
            w._substate_start = time.monotonic() - 121.0
            w._activate_time = time.monotonic() - 121.0
            # Ensure current mode is DEFAULT (after TW-PR-3 expansion)
            w._current_mode = ThinkingMode.DEFAULT
            # Apply DEFAULT CSS class so set_mode has something to swap
            w.remove_class("--mode-compact")
            w.add_class("--mode-default")

            w._tick()
            await pilot.pause()

            assert w.has_class("--mode-deep")
            assert not w.has_class("--mode-default")

    @pytest.mark.asyncio
    async def test_tick_deep_expansion_not_before_deep_after_s(self):
        """ceiling=DEEP, reveal=True, elapsed=60 → no DEEP expansion yet."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w._cfg_deep_after_s = 120.0
            w.activate(mode=ThinkingMode.DEEP)
            await pilot.pause()

            w._substate = "LONG_WAIT"
            w._substate_start = time.monotonic() - 60.0
            w._activate_time = time.monotonic() - 60.0
            w._current_mode = ThinkingMode.DEFAULT
            w.remove_class("--mode-compact")
            w.add_class("--mode-default")

            w._tick()
            await pilot.pause()

            assert not w.has_class("--mode-deep")
            assert w.has_class("--mode-default")

    @pytest.mark.asyncio
    async def test_tick_deep_expansion_ceiling_default_no_deep(self):
        """ceiling=DEFAULT, elapsed=121 → no DEEP expansion (ceiling respected)."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = True
            w._cfg_deep_after_s = 120.0
            w.activate(mode=ThinkingMode.DEFAULT)
            await pilot.pause()

            w._substate = "LONG_WAIT"
            w._substate_start = time.monotonic() - 121.0
            w._activate_time = time.monotonic() - 121.0
            w._current_mode = ThinkingMode.DEFAULT

            w._tick()
            await pilot.pause()

            assert not w.has_class("--mode-deep")

    @pytest.mark.asyncio
    async def test_reveal_false_deep_starts_immediately(self):
        """reveal=False, ceiling=DEEP → activate applies --mode-deep at once."""
        async with _App().run_test(size=(140, 40)) as pilot:
            w = pilot.app.query_one(ThinkingWidget)
            w._cfg_progressive_reveal = False
            w.activate(mode=ThinkingMode.DEEP)
            await pilot.pause()
            assert w.has_class("--mode-deep")
            assert not w.has_class("--mode-compact")
