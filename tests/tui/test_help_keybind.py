"""G1: ? opens context menu; F1 opens help (standard convention)."""
from __future__ import annotations

from textual.binding import Binding

from hermes_cli.tui.tool_panel import ToolPanel


def test_question_mark_bound_to_show_context_menu():
    bindings = {b.key: b.action for b in ToolPanel.BINDINGS if isinstance(b, Binding)}
    assert bindings.get("question_mark") == "show_context_menu"


def test_f1_bound_to_show_help():
    bindings = {b.key: b.action for b in ToolPanel.BINDINGS if isinstance(b, Binding)}
    assert bindings.get("f1") == "show_help"
