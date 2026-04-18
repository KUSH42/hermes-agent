"""Phase D tests: TurnPhase container widgets.

10 tests covering AgentThought, ToolSequence, AgentFinalResponse.
"""
from __future__ import annotations

import pytest
from textual.widget import Widget

from hermes_cli.tui.turn_phase import AgentThought, ToolSequence, AgentFinalResponse


def test_agent_thought_is_widget():
    assert issubclass(AgentThought, Widget)


def test_tool_sequence_is_widget():
    assert issubclass(ToolSequence, Widget)


def test_agent_final_response_is_widget():
    assert issubclass(AgentFinalResponse, Widget)


def test_agent_final_response_multiline_adds_class():
    afr = AgentFinalResponse()
    added = []
    afr.add_class = lambda *a: added.extend(a)
    afr.remove_class = lambda *a: None
    afr.set_multiline(True)
    assert "-multiline" in added


def test_agent_final_response_single_line_no_class():
    afr = AgentFinalResponse()
    removed = []
    afr.add_class = lambda *a: None
    afr.remove_class = lambda *a: removed.extend(a)
    afr.set_multiline(False)
    assert "-multiline" in removed


def test_agent_final_response_remove_multiline_class():
    afr = AgentFinalResponse()
    removed = []
    afr.add_class = lambda *a: None
    afr.remove_class = lambda *a: removed.extend(a)
    afr.set_multiline(False)
    assert "-multiline" in removed


def test_agent_thought_has_border_left_css():
    css = AgentThought.DEFAULT_CSS
    assert "border-left" in css


def test_tool_sequence_composes_without_error():
    ts = ToolSequence()
    assert ts is not None


def test_turn_phase_importable():
    """Importing turn_phase module works without errors."""
    import hermes_cli.tui.turn_phase as tp
    assert hasattr(tp, "AgentThought")
    assert hasattr(tp, "ToolSequence")
    assert hasattr(tp, "AgentFinalResponse")


def test_turn_phase_widgets_have_auto_height():
    for cls in (AgentThought, ToolSequence, AgentFinalResponse):
        assert "auto" in cls.DEFAULT_CSS, f"{cls.__name__} should have height: auto"
