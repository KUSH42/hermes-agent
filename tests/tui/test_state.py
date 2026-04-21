"""Tests for hermes_cli.tui.state — typed overlay state dataclasses."""

import queue
import time

from hermes_cli.tui.state import (
    ChoiceOverlayState,
    OverlayState,
    SecretOverlayState,
)


def test_overlay_state_remaining_positive():
    """remaining returns positive seconds when deadline is in the future."""
    state = OverlayState(
        deadline=time.monotonic() + 10,
        response_queue=queue.Queue(),
    )
    assert state.remaining > 0
    assert state.remaining <= 10


def test_overlay_state_remaining_zero_when_expired():
    """remaining returns 0 when deadline has passed."""
    state = OverlayState(
        deadline=time.monotonic() - 5,
        response_queue=queue.Queue(),
    )
    assert state.remaining == 0


def test_overlay_state_expired_false():
    """expired is False when deadline is in the future."""
    state = OverlayState(
        deadline=time.monotonic() + 60,
        response_queue=queue.Queue(),
    )
    assert not state.expired


def test_overlay_state_expired_true():
    """expired is True when deadline has passed."""
    state = OverlayState(
        deadline=time.monotonic() - 1,
        response_queue=queue.Queue(),
    )
    assert state.expired


def test_choice_overlay_state_defaults():
    """ChoiceOverlayState has correct default values."""
    state = ChoiceOverlayState(
        deadline=time.monotonic() + 30,
        response_queue=queue.Queue(),
    )
    assert state.question == ""
    assert state.choices == []
    assert state.selected == 0


def test_choice_overlay_state_with_values():
    """ChoiceOverlayState stores question, choices, and selection."""
    state = ChoiceOverlayState(
        deadline=time.monotonic() + 30,
        response_queue=queue.Queue(),
        question="Pick one",
        choices=["a", "b", "c"],
        selected=1,
    )
    assert state.question == "Pick one"
    assert state.choices == ["a", "b", "c"]
    assert state.selected == 1


def test_secret_overlay_state_defaults():
    """SecretOverlayState has correct default values."""
    state = SecretOverlayState(
        deadline=time.monotonic() + 30,
        response_queue=queue.Queue(),
    )
    assert state.prompt == ""


def test_secret_overlay_state_with_prompt():
    """SecretOverlayState stores prompt text."""
    state = SecretOverlayState(
        deadline=time.monotonic() + 30,
        response_queue=queue.Queue(),
        prompt="Enter your API key:",
    )
    assert state.prompt == "Enter your API key:"


def test_response_queue_communication():
    """Response queue supports cross-thread communication pattern."""
    q = queue.Queue()
    state = ChoiceOverlayState(
        deadline=time.monotonic() + 30,
        response_queue=q,
        question="Allow?",
        choices=["yes", "no"],
    )
    # Simulate widget putting an answer
    state.response_queue.put("yes")
    # Simulate agent thread reading
    result = state.response_queue.get(timeout=1)
    assert result == "yes"


def test_overlay_state_repr_hides_queue():
    """response_queue is excluded from repr (field(repr=False))."""
    state = OverlayState(
        deadline=0.0,
        response_queue=queue.Queue(),
    )
    r = repr(state)
    assert "Queue" not in r
    assert "deadline" in r
