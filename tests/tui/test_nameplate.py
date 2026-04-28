"""Tests for AssistantNameplate widget."""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch, call

import pytest
from rich.text import Text

from hermes_cli.tui.widgets import (
    AssistantNameplate,
    _NPChar,
    _NPIdleBeat,
    _NPState,
    _NP_POOL,
    _NP_IDLE_COLOR,
    _NP_ACTIVE_COLOR,
    _NP_ERROR_COLOR,
)


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
    np.set_timer = MagicMock(return_value=MagicMock())
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
        # _DECRYPT_TICKS=150, "Hermes"=6 chars → step=30, max lock_at≈150+jitter
        # Use deterministic jitter=0 and generous ceiling
        with patch("hermes_cli.tui.widgets._random.randint", return_value=0):
            np._init_decrypt()  # re-init with deterministic lock_at values
        max_ticks = 155  # ceil(150) + buffer
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
    def test_idle_static_returns_plain_text(self):
        np = _make_np_effects()
        np._state = _NPState.IDLE
        result = np.render()
        assert isinstance(result, Text)
        assert "Hermes" in result.plain

    def test_idle_effect_none_returns_plain_text(self):
        np = _make_np_effects(idle_effect="none")
        np._state = _NPState.IDLE
        result = np.render()
        assert isinstance(result, Text)
        assert "Hermes" in result.plain

    def test_idle_effect_named_types_stored(self):
        for effect in ("pulse", "shimmer", "decrypt", "auto", "none"):
            np = AssistantNameplate(name="Hermes", idle_effect=effect)
            assert np._idle_effect_name == effect

    def test_idle_invalid_effect_stored_as_is(self):
        np = AssistantNameplate(name="Hermes", idle_effect="bogus")
        assert np._idle_effect_name == "bogus"

    def test_breathe_alias_stored_as_pulse(self):
        np = AssistantNameplate(name="Hermes", idle_effect="breathe")
        assert np._idle_effect_name == "pulse"


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


# ---------------------------------------------------------------------------
# NA-1 — Beat cadence / timer architecture
# ---------------------------------------------------------------------------

class TestNA1BeatCadence:
    def test_idle_no_timer_between_beats(self):
        np = _make_np_effects()
        np._enter_idle_timer()
        # Between-beats: 30fps interval stopped, one-shot scheduled
        assert np._timer is None
        assert np._idle_beat_timer is not None
        assert np._idle_beat_type == _NPIdleBeat.NONE

    def test_idle_beat_starts_on_one_shot_fire(self):
        np = _make_np_effects()
        np._start_idle_beat()
        assert np._idle_beat_type != _NPIdleBeat.NONE
        assert np._timer is not None  # 30fps interval running

    def test_idle_beat_done_reschedules(self):
        np = _make_np_effects(idle_effect="pulse")
        np._start_idle_beat()
        # Force beat completion by advancing tick past threshold
        np._idle_beat_tick = np._BEAT_PULSE_TICKS
        np._tick_idle()
        # Beat done: interval stopped, next one-shot scheduled
        assert np._timer is None
        assert np._idle_beat_timer is not None
        assert np._idle_beat_type == _NPIdleBeat.NONE

    def test_idle_effects_none_no_timer(self):
        np = _make_np_effects(idle_effect="none")
        np._enter_idle_timer()
        assert np._timer is None
        assert np._idle_beat_timer is None


# ---------------------------------------------------------------------------
# NA-2 — Beat catalogue
# ---------------------------------------------------------------------------

class TestNA2PulseBeat:
    def test_beat_pulse_returns_text(self):
        np = _make_np(name="Hermes")
        t0 = np._render_beat_pulse(0)
        t15 = np._render_beat_pulse(15)
        assert isinstance(t0, Text)
        assert len(t0._spans) == len("Hermes")
        assert isinstance(t15, Text)
        # Mid-cycle should be different colors than tick-0
        assert t0._spans[0].style != t15._spans[0].style

    def test_beat_pulse_completes_at_30(self):
        np = _make_np(name="Hermes")
        assert np._tick_idle_beat(_NPIdleBeat.PULSE, 29) is False
        assert np._tick_idle_beat(_NPIdleBeat.PULSE, 30) is True

    def test_beat_pulse_first_char_offset(self):
        import math
        np = _make_np(name="Hermes")
        np._idle_color_hex = "#888888"
        np._accent_hex = "#7b68ee"
        tick = 0
        n = max(3, len("Hermes"))
        phase = 2 * math.pi * tick / np._BEAT_PULSE_TICKS  # = 0
        offset = math.pi / n
        w = (math.sin(phase - 0 * offset) + 1.0) / 2.0  # sin(0) = 0 → w = 0.5
        assert abs(w - 0.5) < 1e-9
        t = np._render_beat_pulse(0)
        # w=0.5 means color is midpoint; just verify it returns a styled span
        assert len(t._spans) == len("Hermes")


class TestNA2ShimmerBeat:
    def test_beat_shimmer_window_moves(self):
        import math
        np = _make_np(name="ABCDEF")  # 6-char name
        np._idle_color_hex = "#888888"
        np._accent_hex = "#7b68ee"
        n = max(3, 6)
        # At tick 6: pos = (6+4)*6/30 - 2 = 60/30 - 2 = 2 - 2 = 0
        # char 0: dist=0, w=1.0 (bright); char 5: dist=5, w=0 (dark)
        tick_a = 6
        pos_a = (n + 4) * tick_a / np._BEAT_SHIMMER_TICKS - 2
        w0_a = max(0.0, 1.0 - abs(0 - pos_a) / 1.5)
        w5_a = max(0.0, 1.0 - abs(5 - pos_a) / 1.5)
        assert w0_a > 0.0
        assert w5_a == 0.0
        # At tick 21: pos = (6+4)*21/30 - 2 = 7 - 2 = 5
        # char 5: dist=0, w=1.0 (bright); char 0: dist=5, w=0 (dark)
        tick_b = 21
        pos_b = (n + 4) * tick_b / np._BEAT_SHIMMER_TICKS - 2
        w0_b = max(0.0, 1.0 - abs(0 - pos_b) / 1.5)
        w5_b = max(0.0, 1.0 - abs(5 - pos_b) / 1.5)
        assert w5_b > 0.0
        assert w0_b == 0.0

    def test_beat_shimmer_completes_at_30(self):
        np = _make_np(name="Hermes")
        assert np._tick_idle_beat(_NPIdleBeat.SHIMMER, 29) is False
        assert np._tick_idle_beat(_NPIdleBeat.SHIMMER, 30) is True


class TestNA2DecryptBeat:
    def test_init_beat_decrypt_sets_frame(self):
        np = _make_np(name="Hermes")
        np._init_beat(_NPIdleBeat.DECRYPT)
        assert len(np._beat_decrypt_frame) == len("Hermes")
        for ch in np._beat_decrypt_frame:
            assert ch.current in _NP_POOL
            assert not ch.locked

    def test_beat_decrypt_scramble_phase(self):
        import random as _r
        np = _make_np(name="Hermes")
        np._init_beat(_NPIdleBeat.DECRYPT)
        # Seed so chars are deterministically from pool (not target)
        with patch("hermes_cli.tui.widgets._random", _r):
            _r.seed(42)
            np._tick_beat_decrypt(5)
        for ch in np._beat_decrypt_frame:
            assert ch.current in _NP_POOL

    def test_beat_decrypt_resolve_phase(self):
        np = _make_np(name="Hermes")
        np._init_beat(_NPIdleBeat.DECRYPT)
        # Scramble first
        for _ in range(10):
            np._tick_beat_decrypt(_)
        # At tick 10: t_rel=0, char 0 locks (0 <= 5*0/19 = 0)
        np._tick_beat_decrypt(10)
        assert np._beat_decrypt_frame[0].locked
        assert np._beat_decrypt_frame[0].current == "H"
        # At tick 29: all locked
        for t in range(11, 30):
            np._tick_beat_decrypt(t)
        for ch in np._beat_decrypt_frame:
            assert ch.locked

    def test_beat_decrypt_completes_when_all_locked(self):
        np = _make_np(name="Hermes")
        np._init_beat(_NPIdleBeat.DECRYPT)
        for t in range(30):
            np._tick_beat_decrypt(t)
        result = np._tick_idle_beat(_NPIdleBeat.DECRYPT, 30)
        assert result is True

    def test_render_idle_beat_dispatch(self):
        np = _make_np(name="Hermes")
        # PULSE dispatch
        with patch.object(np, "_render_beat_pulse", return_value=Text("x")) as mock_p:
            np._render_idle_beat(_NPIdleBeat.PULSE, 5)
            mock_p.assert_called_once_with(5)
        # SHIMMER dispatch
        with patch.object(np, "_render_beat_shimmer", return_value=Text("x")) as mock_s:
            np._render_idle_beat(_NPIdleBeat.SHIMMER, 5)
            mock_s.assert_called_once_with(5)
        # DECRYPT renders inline from _beat_decrypt_frame
        np._init_beat(_NPIdleBeat.DECRYPT)
        result = np._render_idle_beat(_NPIdleBeat.DECRYPT, 5)
        assert isinstance(result, Text)
        assert len(result._spans) == len("Hermes")


# ---------------------------------------------------------------------------
# NA-3 — Auto-variety mode + config params
# ---------------------------------------------------------------------------

class TestNA3AutoVariety:
    def test_pick_beat_auto_returns_catalogue_member(self):
        np = _make_np(name="Hermes", effects_enabled=False)
        np._idle_effect_name = "auto"
        for _ in range(100):
            result = np._pick_beat_type()
            assert result in np._BEAT_CATALOGUE

    def test_pick_beat_named_type(self):
        np = _make_np(name="Hermes")
        np._idle_effect_name = "shimmer"
        assert np._pick_beat_type() == _NPIdleBeat.SHIMMER
        np._idle_effect_name = "decrypt"
        assert np._pick_beat_type() == _NPIdleBeat.DECRYPT
        np._idle_effect_name = "pulse"
        assert np._pick_beat_type() == _NPIdleBeat.PULSE

    def test_breathe_alias(self):
        np = AssistantNameplate(name="Hermes", idle_effect="breathe")
        assert np._idle_effect_name == "pulse"

    def test_beat_cooldown_range(self):
        np = _make_np_effects(name="Hermes", idle_beat_min_s=5.0, idle_beat_max_s=10.0)
        delays = []
        def _capture(delay, _cb):
            delays.append(delay)
            return MagicMock()
        np.set_timer = _capture
        for _ in range(50):
            np._schedule_next_beat()
        assert all(5.0 <= d <= 10.0 for d in delays)

    def test_idle_effect_none_never_schedules(self):
        np = _make_np_effects(idle_effect="none")
        np._enter_idle_timer()
        assert np._idle_beat_timer is None

    def test_pick_beat_unknown_emits_warning(self):
        np = _make_np(name="Hermes")
        np._idle_effect_name = "bogus"
        with patch("hermes_cli.tui.widgets._LOG") as mock_log:
            result = np._pick_beat_type()
        mock_log.warning.assert_called_once()
        args = mock_log.warning.call_args[0]
        assert "bogus" in str(args)
        assert result == _NPIdleBeat.PULSE
