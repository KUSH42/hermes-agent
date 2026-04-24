"""
SplitTargetStub — pre-mounted placeholder for the split bottom slot.
display: none until Ctrl+\\ toggles it.
"""
from __future__ import annotations
from textual.widgets import Static


class SplitTargetStub(Static):
    DEFAULT_CSS = """
    SplitTargetStub {
        color: $text-muted;
        padding: 1 2;
        height: 1fr;
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            "Split target — set from command palette",
            **kwargs,
        )
