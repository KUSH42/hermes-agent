"""TurnPhase container widgets — Phase D infrastructure.

Three containers that semantically group content within a conversation turn:
  AgentThought    — streaming reasoning / thinking content
  ToolSequence    — contiguous tool panels within a turn
  AgentFinalResponse — final markdown response text

Activation of TurnPhase wrapping is gated behind config flag
``display.tool_panel_v3_turn_phases`` (default False) — Phase E will flip it.
"""
from __future__ import annotations

from textual.widget import Widget


class AgentThought(Widget):
    """Container for streaming reasoning/thinking content."""

    DEFAULT_CSS = """
    AgentThought {
        height: auto;
        border-left: vkey $primary 20%;
        padding: 0 0 0 1;
    }
    """


class ToolSequence(Widget):
    """Container for contiguous tool panels within a turn."""

    DEFAULT_CSS = "ToolSequence { height: auto; }"


class AgentFinalResponse(Widget):
    """Container for the final markdown turn response."""

    DEFAULT_CSS = """
    AgentFinalResponse {
        height: auto;
    }
    AgentFinalResponse.-multiline {
        border-left: vkey $primary 20%;
        padding: 0 0 0 1;
    }
    """

    def set_multiline(self, is_multi: bool) -> None:
        """Toggle -multiline class based on whether response spans >1 line."""
        if is_multi:
            self.add_class("-multiline")
        else:
            self.remove_class("-multiline")
