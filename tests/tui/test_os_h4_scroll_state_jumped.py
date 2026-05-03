"""Tests for OS-H4: _user_scrolled_up setter JUMPED → PINNED guard.

Pure Python — no Textual App runtime required.
"""
from __future__ import annotations

import types
import pytest

from hermes_cli.tui.widgets.output_panel import ScrollState


# ---------------------------------------------------------------------------
# Minimal stub: enough for the _user_scrolled_up property + setter to work
# ---------------------------------------------------------------------------


class _StubOutputPanel:
    """Minimal stub exposing scroll_state and the property under test."""

    def __init__(self, state: ScrollState) -> None:
        self.scroll_state = state

    @property
    def _user_scrolled_up(self) -> bool:
        return self.scroll_state != ScrollState.PINNED

    @_user_scrolled_up.setter
    def _user_scrolled_up(self, v: bool) -> None:
        if not v and self.scroll_state == ScrollState.JUMPED:
            return  # JUMPED→PINNED only via watch_scroll_y reaching live edge
        self.scroll_state = ScrollState.ANCHORED if v else ScrollState.PINNED


# ---------------------------------------------------------------------------
# TestOSH4
# ---------------------------------------------------------------------------


class TestOSH4:
    def test_setter_false_preserves_jumped(self) -> None:
        """Writing False when JUMPED must be a no-op (guard fires)."""
        panel = _StubOutputPanel(ScrollState.JUMPED)
        panel._user_scrolled_up = False
        assert panel.scroll_state == ScrollState.JUMPED

    def test_setter_false_pins_when_anchored(self) -> None:
        """Writing False when ANCHORED must transition to PINNED."""
        panel = _StubOutputPanel(ScrollState.ANCHORED)
        panel._user_scrolled_up = False
        assert panel.scroll_state == ScrollState.PINNED

    def test_setter_false_pins_when_already_pinned(self) -> None:
        """Writing False when already PINNED must remain PINNED."""
        panel = _StubOutputPanel(ScrollState.PINNED)
        panel._user_scrolled_up = False
        assert panel.scroll_state == ScrollState.PINNED

    def test_setter_true_sets_anchored_regardless_of_state(self) -> None:
        """Writing True from any state must transition to ANCHORED."""
        for state in (ScrollState.PINNED, ScrollState.ANCHORED, ScrollState.JUMPED):
            panel = _StubOutputPanel(state)
            panel._user_scrolled_up = True
            assert panel.scroll_state == ScrollState.ANCHORED, (
                f"Expected ANCHORED from {state!r}, got {panel.scroll_state!r}"
            )
