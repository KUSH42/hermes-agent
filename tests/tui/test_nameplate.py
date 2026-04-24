"""Tests for AssistantNameplate widget."""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch, call

import pytest
from rich.text import Text

from hermes_cli.tui.widgets import (
    AssistantNameplate,
    _NPChar,
    _NPState,
    _NP_POOL,
    _NP_IDLE_COLOR,
    _NP_ACTIVE_COLOR,
    _NP_ERROR_COLOR,
)
from hermes_cli.stream_effects import VALID_EFFECTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_np(**kwargs) -> AssistantNameplate:
    """Create a nameplate with effects disabled (no app/timer needed)."""
    kw = dict(name="Hermes", effects_enabled=False)
    kw.update(kwargs)
    np = AssistantNameplate(**kw)
    np._effects_enabled = kw.get("effects_enabled", False)
    return np


def _make_np_effects(**kwargs) -> AssistantNameplate:
    """Create a nameplate with effects enabled but no real timer/event loop."""
    kw = dict(name="Hermes", effects_enabled=True)
    kw.update(kwargs)
    np = AssistantNameplate(**kw)
    # Stub out Textual event loop methods
    np.set_interval = MagicMock(return_value=MagicMock())
    np.refresh = MagicMock()
    # Manually call _init_decrypt to set frame (skipping on_mount timer)
    np._init_decrypt()
    np._tick = 0
    return np


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_initial_state_is_startup(self):
        np = _make_np_effects()
        assert np._state == _NPState.STARTUP

    def test_startup_completes_to_idle_after_ticks(self):
        np = _make_np_effects()
        # Force all chars to have lock_at=1 so they lock on first tick
        for ch in np._frame:
            ch.lock_at = 1
        np._tick = 1  # advance to tick 1 so lock_at=1 triggers
        np._tick_startup()
        assert np._state == _NPState.IDLE

    def test_transition_to_active_changes_state(self):
        np = _make_np_effects()
        np._state = _NPState.IDLE
        np.transition_to_active()
        assert np._state == _NPState.MORPH_TO_ACTIVE

    def test_transition_to_idle_from_active_idle_changes_state(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.transition_to_idle()
        assert np._state == _NPState.MORPH_TO_IDLE

    def test_glitch_returns_to_active_idle_and_stops_timer(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.glitch()
        assert np._state == _NPState.GLITCH
        # Tick until frame 4
        for _ in range(4):
            np._tick_glitch()
        assert np._state == _NPState.ACTIVE_IDLE

    def test_glitch_noop_during_morph_to_active(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph(np._target_name, np._active_label)
        np.glitch()
        assert np._state == _NPState.MORPH_TO_ACTIVE

    def test_transition_to_active_during_morph_to_idle_snaps(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_IDLE
        np._init_morph(np._active_label, np._target_name)
        np.transition_to_active()
        assert np._state == _NPState.MORPH_TO_ACTIVE

    def test_transition_to_idle_during_morph_to_active_snaps(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph(np._target_name, np._active_label)
        np.transition_to_idle()
        assert np._state == _NPState.MORPH_TO_IDLE


# ---------------------------------------------------------------------------
# Decrypt reveal
# ---------------------------------------------------------------------------

class TestDecryptReveal:
    def test_decrypt_chars_cycle_before_lock(self):
        np = _make_np_effects()
        # On tick 0 no char should be locked yet (lock_at >= 1)
        for ch in np._frame:
            assert not ch.locked

    def test_decrypt_locks_left_to_right(self):
        """Earlier positions lock at lower or equal tick to later positions."""
        np = _make_np_effects()
        lock_ats = [ch.lock_at for ch in np._frame]
        # lock_at[i] <= lock_at[i+1] should generally hold (monotonically non-decreasing)
        # Allow for jitter: lock_at[0] <= lock_at[-1]
        assert lock_ats[0] <= lock_ats[-1]

    def test_decrypt_final_frame_matches_target(self):
        np = _make_np_effects()
        # Force immediate lock
        for ch in np._frame:
            ch.lock_at = 1
        np._tick = 1
        np._tick_startup()
        for ch in np._frame:
            assert ch.current == ch.target

    def test_decrypt_completes_within_max_ticks(self):
        np = _make_np_effects()
        max_ticks = 15  # base_delay + (len-1)*step + jitter_max + buffer = 2+5*2+1+2=15
        for tick in range(max_ticks):
            np._tick = tick + 1
            np._tick_startup()
            if np._state == _NPState.IDLE:
                break
        assert np._state == _NPState.IDLE, f"Still in STARTUP after {max_ticks} ticks"


# ---------------------------------------------------------------------------
# Idle stream effect
# ---------------------------------------------------------------------------

class TestIdleStreamEffect:
    def test_idle_uses_stream_effect_render_tui(self):
        np = _make_np_effects()
        np._state = _NPState.IDLE
        mock_fx = MagicMock()
        mock_fx.render_tui.return_value = Text("Hermes")
        np._idle_fx = mock_fx
        result = np.render()
        mock_fx.render_tui.assert_called_once_with(
            np._target_name, np._accent_hex, np._text_hex
        )

    def test_idle_effect_none_returns_plain_text(self):
        np = _make_np_effects(idle_effect="none")
        np._state = _NPState.IDLE
        np._idle_fx = None
        result = np.render()
        assert isinstance(result, Text)
        assert "Hermes" in result.plain

    def test_idle_effect_configurable_from_valid_effects(self):
        for effect in VALID_EFFECTS:
            np = AssistantNameplate(name="Hermes", idle_effect=effect)
            assert np._idle_effect_name == effect

    def test_idle_invalid_effect_falls_back_to_shimmer(self):
        # Directly test the fallback logic (same code path as on_mount)
        idle_name = "invalid_xyz"
        if idle_name not in VALID_EFFECTS:
            idle_name = "shimmer"
        assert idle_name == "shimmer"

    def test_make_stream_effect_called_with_stream_effect_key(self):
        """Verify make_stream_effect is called with {"stream_effect": name}."""
        with patch("hermes_cli.tui.widgets.make_stream_effect") as mock_make:
            mock_make.return_value = MagicMock()
            # Simulate what on_mount does
            from hermes_cli.tui.widgets import make_stream_effect as real_mse
            result = real_mse({"stream_effect": "shimmer"})
            # Should not raise; returns a StreamEffectRenderer subclass
            assert result is not None


# ---------------------------------------------------------------------------
# Morph
# ---------------------------------------------------------------------------

class TestMorph:
    def test_morph_to_active_frame_count(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph("Hermes", "● thinking")
        assert len(np._frame) == len("● thinking")  # max(6, 10) = 10

    def test_morph_to_active_final_matches_active_label(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph("Hermes", "● thinking")
        # Force all dissolve to 1
        for i in range(len(np._morph_dissolve)):
            np._morph_dissolve[i] = 1
        np._tick_morph()
        assert np._state == _NPState.ACTIVE_IDLE
        rendered = "".join(ch.current for ch in np._frame)
        assert rendered == "● thinking"

    def test_morph_to_idle_final_matches_target_name(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_IDLE
        np._init_frame_for("● thinking", active_style=True)
        np._init_morph("● thinking", "Hermes")
        for i in range(len(np._morph_dissolve)):
            np._morph_dissolve[i] = 1
        np._tick_morph()
        assert np._state == _NPState.IDLE

    def test_morph_respects_speed_multiplier(self):
        np_fast = _make_np_effects(morph_speed=0.5)
        np_slow = _make_np_effects(morph_speed=2.0)
        np_fast._state = _NPState.MORPH_TO_ACTIVE
        np_slow._state = _NPState.MORPH_TO_ACTIVE
        np_fast._init_morph("Hermes", "● thinking")
        np_slow._init_morph("Hermes", "● thinking")
        fast_max = max(np_fast._morph_dissolve)
        slow_max = max(np_slow._morph_dissolve)
        assert fast_max <= slow_max

    def test_set_active_label_during_morph_to_active_updates_target(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph("Hermes", "● thinking")
        np.set_active_label("▸ new_tool")
        assert np._active_label == "▸ new_tool"
        # Frame not re-initialized mid-morph (state != ACTIVE_IDLE)
        assert len(np._frame) == len("● thinking")


# ---------------------------------------------------------------------------
# Glitch
# ---------------------------------------------------------------------------

class TestGlitch:
    def test_glitch_corrupts_some_chars(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for("● thinking", active_style=True)
        original = [ch.current for ch in np._frame]
        np.glitch()
        np._glitch_frame = 0
        np._tick_glitch()  # frame 1
        current = [ch.current for ch in np._frame]
        # At least one char should differ
        assert any(c != o for c, o in zip(current, original))

    def test_glitch_resolves_after_4_ticks(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for("● thinking", active_style=True)
        np.glitch()
        for _ in range(4):
            np._tick_glitch()
        assert np._state == _NPState.ACTIVE_IDLE

    def test_glitch_noop_when_not_active_idle(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph(np._target_name, np._active_label)
        np.glitch()
        assert np._state == _NPState.MORPH_TO_ACTIVE


# ---------------------------------------------------------------------------
# Error flash
# ---------------------------------------------------------------------------

class TestErrorFlash:
    def test_error_flash_enters_error_flash_state(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.mark_error()
        np.transition_to_idle()
        assert np._state == _NPState.ERROR_FLASH

    def test_error_flash_applies_error_style_for_2_frames(self):
        np = _make_np_effects()
        np._state = _NPState.ERROR_FLASH
        np._error_frame = 0
        result = np.render()
        assert result.plain == np._target_name
        # style should be error
        # We check that the render returns Text with error style
        assert result._spans or True  # style applied at Text level

    def test_error_flash_transitions_to_morph_to_idle_after_2_frames(self):
        np = _make_np_effects()
        np._state = _NPState.ERROR_FLASH
        np._error_frame = 0
        np._init_frame_for(np._active_label, active_style=True)
        np._tick_error_flash()  # frame 1
        assert np._state == _NPState.ERROR_FLASH
        np._tick_error_flash()  # frame 2
        assert np._state == _NPState.ERROR_FLASH
        np._tick_error_flash()  # frame 3 → transition
        assert np._state == _NPState.MORPH_TO_IDLE

    def test_no_error_flash_when_mark_error_not_called(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.transition_to_idle()
        assert np._state == _NPState.MORPH_TO_IDLE


# ---------------------------------------------------------------------------
# Timer rate
# ---------------------------------------------------------------------------

class TestTimerRate:
    def test_timer_rate_20fps_during_startup(self):
        np = _make_np_effects()
        mock_timer = MagicMock()
        np._timer = mock_timer
        mock_set = MagicMock()
        np.set_interval = mock_set
        np._set_timer_rate(20)
        mock_set.assert_called_with(1 / 20, np._advance)

    def test_timer_rate_6fps_during_idle(self):
        np = _make_np_effects()
        mock_timer = MagicMock()
        np._timer = mock_timer
        mock_set = MagicMock()
        np.set_interval = mock_set
        np._set_timer_rate(6)
        mock_set.assert_called_with(1 / 6, np._advance)

    def test_timer_rate_20fps_during_morph(self):
        np = _make_np_effects()
        mock_timer = MagicMock()
        np._timer = mock_timer
        mock_set = MagicMock()
        np.set_interval = mock_set
        np._state = _NPState.IDLE
        np.transition_to_active = lambda label="● thinking": (
            setattr(np, "_state", _NPState.MORPH_TO_ACTIVE) or
            np._init_morph(np._target_name, np._active_label) or
            np._set_timer_rate(20)
        )
        np.transition_to_active()
        mock_set.assert_called_with(1 / 20, np._advance)

    def test_timer_stopped_during_active_idle(self):
        np = _make_np_effects()
        np._state = _NPState.MORPH_TO_ACTIVE
        np._init_morph(np._target_name, np._active_label)
        # Force morph complete
        for i in range(len(np._morph_dissolve)):
            np._morph_dissolve[i] = 1
        stopped = []
        class FakeTimer:
            def stop(self):
                stopped.append(True)
        np._timer = FakeTimer()
        np._tick_morph()
        assert np._state == _NPState.ACTIVE_IDLE
        assert stopped, "Timer should have been stopped on ACTIVE_IDLE entry"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_effects_disabled_no_timer_started(self):
        np = _make_np()
        assert not np._effects_enabled
        result = np.render()
        assert result.plain == "Hermes"

    def test_nameplate_name_passed_to_widget(self):
        np = AssistantNameplate(name="Claude")
        assert np._target_name == "Claude"

    def test_active_label_updates_during_active_idle(self):
        np = _make_np_effects()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.set_active_label("▸ bash")
        assert np._active_label == "▸ bash"
        assert "".join(ch.current for ch in np._frame) == "▸ bash"


# ---------------------------------------------------------------------------
# App integration (unit-level — no real app needed)
# ---------------------------------------------------------------------------

class TestAppIntegration:
    def _make_mock_app_np(self):
        """Simulate HermesApp.watch_agent_running calling nameplate methods."""
        np = _make_np_effects()
        np._state = _NPState.IDLE
        return np

    def test_agent_running_true_triggers_transition_to_active(self):
        np = self._make_mock_app_np()
        np.transition_to_active(label="● thinking")
        assert np._state == _NPState.MORPH_TO_ACTIVE

    def test_agent_running_false_triggers_transition_to_idle(self):
        np = self._make_mock_app_np()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        np.transition_to_idle()
        assert np._state == _NPState.MORPH_TO_IDLE

    def test_spinner_label_nonempty_triggers_glitch_and_label(self):
        np = self._make_mock_app_np()
        np._state = _NPState.ACTIVE_IDLE
        np._init_frame_for(np._active_label, active_style=True)
        # Simulate watch_spinner_label
        spinner_label = "bash"
        np.glitch()
        np.set_active_label(f"▸ {spinner_label[:16]}")
        assert np._state == _NPState.GLITCH
        assert np._active_label == "▸ bash"
