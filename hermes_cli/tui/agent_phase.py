"""Phase constants for agent lifecycle — A1."""
from __future__ import annotations


class Phase:
    IDLE      = "idle"
    REASONING = "reasoning"
    STREAMING = "streaming"
    TOOL_EXEC = "tool_exec"
    ERROR     = "error"
