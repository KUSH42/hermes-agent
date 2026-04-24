"""Placeholder for R6/R9 Context Panel."""
from __future__ import annotations
from textual.widgets import Static


class ContextPanelStub(Static):
    DEFAULT_CSS = """
    ContextPanelStub {
        color: $text-muted;
        padding: 1 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("Context will appear here — R6/R9", **kwargs)
