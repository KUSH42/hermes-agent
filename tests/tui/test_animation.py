"""Unit tests for hermes_cli/tui/animation.py — pure functions and PulseMixin.

Run with:
    pytest -o "addopts=" tests/tui/test_animation.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# lerp
# ---------------------------------------------------------------------------

def test_lerp_at_zero():
    from hermes_cli.tui.animation import lerp
    assert lerp(0.0, 10.0, 0.0) == pytest.approx(0.0)


def test_lerp_at_one():
    from hermes_cli.tui.animation import lerp
    assert lerp(0.0, 10.0, 1.0) == pytest.approx(10.0)


def test_lerp_at_half():
    from hermes_cli.tui.animation import lerp
    assert lerp(0.0, 10.0, 0.5) == pytest.approx(5.0)


def test_lerp_negative_range():
    from hermes_cli.tui.animation import lerp
    assert lerp(10.0, 0.0, 0.25) == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# ease_out_cubic
# ---------------------------------------------------------------------------

def test_ease_out_cubic_at_zero():
    from hermes_cli.tui.animation import ease_out_cubic
    assert ease_out_cubic(0.0) == pytest.approx(0.0)


def test_ease_out_cubic_at_one():
    from hermes_cli.tui.animation import ease_out_cubic
    assert ease_out_cubic(1.0) == pytest.approx(1.0)


def test_ease_out_cubic_fast_start():
    from hermes_cli.tui.animation import ease_out_cubic
    # At t=0.5 the output should be > 0.5 (fast start, decelerating)
    assert ease_out_cubic(0.5) > 0.5


# ---------------------------------------------------------------------------
# ease_in_out_cubic
# ---------------------------------------------------------------------------

def test_ease_in_out_cubic_at_zero():
    from hermes_cli.tui.animation import ease_in_out_cubic
    assert ease_in_out_cubic(0.0) == pytest.approx(0.0)


def test_ease_in_out_cubic_at_one():
    from hermes_cli.tui.animation import ease_in_out_cubic
    assert ease_in_out_cubic(1.0) == pytest.approx(1.0)


def test_ease_in_out_cubic_symmetry():
    from hermes_cli.tui.animation import ease_in_out_cubic
    # S-curve: f(t) + f(1-t) == 1 for all t
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert ease_in_out_cubic(t) + ease_in_out_cubic(1.0 - t) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# pulse_phase
# ---------------------------------------------------------------------------

def test_pulse_phase_at_zero():
    from hermes_cli.tui.animation import pulse_phase
    # sin(0) + 1) / 2 == 0.5
    assert pulse_phase(0) == pytest.approx(0.5)


def test_pulse_phase_at_quarter_period():
    from hermes_cli.tui.animation import pulse_phase
    # At tick = period/4: sin(pi/2) == 1.0 → phase == 1.0
    assert pulse_phase(period=30, tick=30 // 4) == pytest.approx(1.0, abs=0.05)


def test_pulse_phase_bounded():
    from hermes_cli.tui.animation import pulse_phase
    for tick in range(0, 120):
        v = pulse_phase(tick, period=30)
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# lerp_color
# ---------------------------------------------------------------------------

def test_lerp_color_at_zero_returns_first():
    from hermes_cli.tui.animation import lerp_color
    assert lerp_color("#000000", "#ffffff", 0.0) == "#000000"


def test_lerp_color_at_one_returns_second():
    from hermes_cli.tui.animation import lerp_color
    assert lerp_color("#000000", "#ffffff", 1.0) == "#ffffff"


def test_lerp_color_midpoint():
    from hermes_cli.tui.animation import lerp_color
    result = lerp_color("#000000", "#ffffff", 0.5)
    # Each channel should be ~0x80 (128)
    assert result.startswith("#")
    r = int(result[1:3], 16)
    g = int(result[3:5], 16)
    b = int(result[5:7], 16)
    assert r == pytest.approx(128, abs=1)
    assert g == pytest.approx(128, abs=1)
    assert b == pytest.approx(128, abs=1)


def test_lerp_color_no_hash_prefix():
    """lerp_color accepts colors without leading #."""
    from hermes_cli.tui.animation import lerp_color
    result = lerp_color("ff0000", "0000ff", 0.5)
    assert result.startswith("#")
    assert len(result) == 7


def test_lerp_color_known_values():
    from hermes_cli.tui.animation import lerp_color
    # #ffa726 → #ef5350 at t=1/3
    t = 1 / 3
    result = lerp_color("#ffa726", "#ef5350", t)
    r_expected = round(0xff + (0xef - 0xff) * t)
    g_expected = round(0xa7 + (0x53 - 0xa7) * t)
    b_expected = round(0x26 + (0x50 - 0x26) * t)
    assert result == f"#{r_expected:02x}{g_expected:02x}{b_expected:02x}"


# ---------------------------------------------------------------------------
# PulseMixin
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Minimal duck-typed stub for PulseMixin's Widget duck-typing."""

    def __init__(self):
        self._timer_callbacks = []
        self._refreshed = 0

    def set_interval(self, interval, callback):
        handle = MagicMock()
        handle._callback = callback
        handle._stopped = False
        def stop():
            handle._stopped = True
        handle.stop = stop
        self._timer_callbacks.append(handle)
        return handle

    def refresh(self):
        self._refreshed += 1


def _make_pulse_widget():
    from hermes_cli.tui.animation import PulseMixin

    class _PW(_FakeWidget, PulseMixin):
        pass

    return _PW()


def test_pulse_start_idempotent():
    """Calling _pulse_start twice only creates one timer."""
    w = _make_pulse_widget()
    w._pulse_start()
    w._pulse_start()
    assert len(w._timer_callbacks) == 1


def test_pulse_step_advances_pulse_t():
    """_pulse_step increments tick and updates _pulse_t."""
    w = _make_pulse_widget()
    w._pulse_start()
    w._pulse_step()
    assert w._pulse_tick == 1
    assert w._pulse_t > 0.0


def test_pulse_stop_resets_pulse_t():
    """_pulse_stop cancels timer and resets _pulse_t to 0."""
    w = _make_pulse_widget()
    w._pulse_start()
    w._pulse_step()
    assert w._pulse_t > 0.0
    w._pulse_stop()
    assert w._pulse_t == 0.0
    assert w._pulse_timer is None


def test_pulse_stop_without_start_is_safe():
    """_pulse_stop is a no-op when no timer is running."""
    w = _make_pulse_widget()
    w._pulse_stop()  # must not raise
    assert w._pulse_t == 0.0
